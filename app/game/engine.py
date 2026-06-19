"""FSM da partida + cronômetro assíncrono + builders das mensagens WS."""
from __future__ import annotations

import asyncio
import logging
import time

from app.config import settings
from app.data.questions import build_deck
from app.game.manager import manager
from app.game.scoring import compute_score, normalize
from app.game.state import GameState, Player, Room
from app.media import cloudinary as cdn
from app.media import warm
from app.models.schemas import MediaType, Question

logger = logging.getLogger("ldkquiz.engine")

REVEAL_PAUSE = 4.0
VIDEO_REVEAL_PAUSE = 6.0
STARTING_PAUSE = 2.0

AUDIO_BUFFER_SECONDS = 5   # áudio servido = duração do round + folga
WARM_AWAIT_TIMEOUT = 10.0  # teto p/ aquecer a questão imminente antes de começar


def _audio_seconds(room: Room) -> int:
    return int(room.round_duration) + AUDIO_BUFFER_SECONDS


def _video_audio_source(q: Question) -> str | None:
    """Fonte de áudio p/ questões de vídeo: o .ogg separado (pequeno, transcoda no
    Cloudinary) em vez do .webm gigante. Fallback: o próprio .webm (legado/sem ogg)."""
    return (q.metadata or {}).get("audio_url") or q.media_url


def _media_payload(q: Question, level: int, audio_seconds: int) -> dict:
    """Mídia para o round. Imagens são progressivas (level); áudio/vídeo vêm completos de uma vez."""
    if q.media_type == MediaType.IMAGE and q.media_url:
        return {"kind": "image", "url": cdn.pixel_image_url(q.media_url, level)}
    if q.media_type == MediaType.AUDIO and q.media_url:
        return {"kind": "audio", "url": cdn.full_audio_url(q.media_url)}
    if q.media_type == MediaType.VIDEO and q.media_url:
        src = _video_audio_source(q)
        return {"kind": "audio", "url": cdn.question_audio_url(src, audio_seconds)}
    return {"kind": "text", "clues": q.clues[: level + 1]}


def _media_reveal(q: Question) -> dict:
    """Mídia completa — só chega aqui no REVEAL."""
    if q.media_type == MediaType.IMAGE and q.media_url:
        return {"kind": "image", "url": cdn.full_image_url(q.media_url)}
    if q.media_type == MediaType.AUDIO and q.media_url:
        return {"kind": "audio", "url": cdn.full_audio_url(q.media_url)}
    if q.media_type == MediaType.VIDEO and q.media_url:
        # .webm cru direto do AnimeThemes: o browser faz Range nativo, sem Cloudinary
        # (fontes grandes estouram o transcode síncrono). Caveat: Safari/iOS não toca webm.
        return {"kind": "video", "url": q.media_url}
    return {"kind": "text", "clues": q.clues}


def _players_public(room: Room) -> list[dict]:
    return [
        {"id": p.id, "name": p.name, "score": p.score, "is_host": p.is_host}
        for p in room.players.values()
    ]


def msg_lobby_update(room: Room) -> dict:
    return {
        "type": "lobby_update",
        "code": room.code,
        "state": room.state.value,
        "host_id": room.host_id,
        "players": _players_public(room),
        "settings": {
            "categories": room.categories,
            "total_rounds": room.total_rounds,
            "round_duration": room.round_duration,
            "allow_multiple_attempts": room.allow_multiple_attempts,
            "end_on_all_correct": room.end_on_all_correct,
        },
    }


def msg_round_paused(room: Room) -> dict:
    return {"type": "round_paused", "time_left": max(0, int(room.round_duration) - room.current_round)}


def msg_round_resumed() -> dict:
    return {"type": "round_resumed"}


def msg_question_start(room: Room) -> dict:
    q = room.current_question
    assert q is not None
    # Nenhuma URL de resposta vaza aqui: VIDEO só manda o áudio; o vídeo fica para o REVEAL.
    return {
        "type": "question_start",
        "round": room.current_round,
        "total_rounds": room.total_rounds,
        "category": q.category,
        "media_type": q.media_type.value,
        "duration": room.round_duration,
        "media": _media_payload(q, 0, _audio_seconds(room)),
    }


def msg_reveal_update(room: Room, elapsed_sec: int, level: int) -> dict:
    q = room.current_question
    assert q is not None
    time_left = max(0, int(room.round_duration) - (elapsed_sec + 1))
    return {
        "type": "reveal_update",
        "level": level,
        "time_left": time_left,
        "media": _media_payload(q, level, _audio_seconds(room)),
    }


def msg_reveal_answer(room: Room) -> dict:
    q = room.current_question
    assert q is not None
    return {
        "type": "reveal_answer",
        "answer": q.answer,
        "media": _media_reveal(q),
        "results": [
            {"id": p.id, "name": p.name, "correct": p.last_correct, "score": p.score}
            for p in room.players.values()
        ],
    }


def msg_scoreboard(room: Room) -> dict:
    ranking = sorted(room.players.values(), key=lambda p: p.score, reverse=True)
    return {
        "type": "scoreboard",
        "round": room.current_round,
        "total_rounds": room.total_rounds,
        "ranking": [{"name": p.name, "score": p.score} for p in ranking],
    }


def msg_game_over(room: Room) -> dict:
    ranking = sorted(room.players.values(), key=lambda p: p.score, reverse=True)
    return {
        "type": "game_over",
        "ranking": [{"name": p.name, "score": p.score} for p in ranking],
    }


async def run_round(room: Room) -> None:
    q = room.current_question
    assert q is not None
    for p in room.players.values():
        p.answered = False
        p.last_correct = False

    # Garante que a mídia desta questão já está quente no Cloudinary antes de começar
    # (o warm_deck normalmente já a aqueceu; aqui é a rede de segurança do round atual).
    await warm.ensure_warm(q, _audio_seconds(room), timeout=WARM_AWAIT_TIMEOUT)

    room.paused = False
    room.round_skip = False
    room.state = GameState.QUESTION
    room.round_started_at = time.monotonic()
    await manager.broadcast(room, msg_question_start(room))

    duration = int(room.round_duration)
    for sec in range(duration):
        # pausa: congela o tick até o host retomar
        while room.paused:
            await asyncio.sleep(0.2)

        await asyncio.sleep(1)

        if room.round_skip:
            break

        level = cdn.reveal_level_for(sec, room.round_duration)
        await manager.broadcast(room, msg_reveal_update(room, sec, level))

    room.state = GameState.REVEAL
    await manager.broadcast(room, msg_reveal_answer(room))

    # Pausa para o cliente ver a resposta/vídeo antes do scoreboard
    q = room.current_question
    reveal_pause = VIDEO_REVEAL_PAUSE if q and q.media_type == MediaType.VIDEO else REVEAL_PAUSE
    await asyncio.sleep(reveal_pause)

    room.state = GameState.SCOREBOARD
    await manager.broadcast(room, msg_scoreboard(room))


async def run_game(room: Room) -> None:
    """STARTING → N rounds → FINISHED. Roda como room.task."""
    try:
        for p in room.players.values():
            p.score = 0

        room.state = GameState.STARTING
        room.deck = build_deck(room.categories, room.total_rounds)
        if not room.deck:
            await manager.broadcast(room, {"type": "error", "message": "Sem questões para as categorias escolhidas."})
            room.state = GameState.LOBBY
            await manager.broadcast(room, msg_lobby_update(room))
            return

        room.total_rounds = len(room.deck)

        # Aquece o cache do Cloudinary p/ TODO o deck em background — o servidor paga
        # o custo do transcode frio antes dos clientes pedirem (vai ficando pronto à frente).
        audio_secs = _audio_seconds(room)
        room.warm_task = asyncio.create_task(warm.warm_deck(room.deck, audio_secs))

        await manager.broadcast(room, {"type": "game_starting", "total_rounds": room.total_rounds})
        await asyncio.sleep(STARTING_PAUSE)

        for idx, question in enumerate(room.deck):
            room.current_round = idx + 1
            room.current_question = question
            await run_round(room)
            await asyncio.sleep(STARTING_PAUSE)  # pausa entre scoreboard e próximo round

        room.state = GameState.FINISHED
        await manager.broadcast(room, msg_game_over(room))
    except asyncio.CancelledError:
        logger.info("Partida da sala %s cancelada", room.code)
        raise
    finally:
        if room.warm_task and not room.warm_task.done():
            room.warm_task.cancel()
        room.warm_task = None
        room.current_question = None
        room.round_started_at = None
        room.task = None
        if room.state != GameState.FINISHED:
            room.state = GameState.LOBBY
        else:
            room.state = GameState.LOBBY
            room.current_round = 0


def start_game(
    room: Room,
    categories: list[str],
    total_rounds: int | None,
    round_duration: float | None = None,
    allow_multiple_attempts: bool | None = None,
    end_on_all_correct: bool | None = None,
) -> bool:
    """Dispara a partida. Retorna False se já rolando."""
    if room.task and not room.task.done():
        return False
    room.categories = categories or []
    room.total_rounds = total_rounds or settings.default_total_rounds
    if round_duration is not None:
        room.round_duration = max(5.0, min(120.0, round_duration))
    if allow_multiple_attempts is not None:
        room.allow_multiple_attempts = allow_multiple_attempts
    if end_on_all_correct is not None:
        room.end_on_all_correct = end_on_all_correct
    room.task = asyncio.create_task(run_game(room))
    return True


async def handle_pause(room: Room) -> None:
    if room.state != GameState.QUESTION or room.paused:
        return
    room.paused = True
    await manager.broadcast(room, {"type": "round_paused"})


async def handle_resume(room: Room) -> None:
    if not room.paused:
        return
    room.paused = False
    await manager.broadcast(room, {"type": "round_resumed"})


async def handle_answer(room: Room, player: Player, guess: str) -> None:
    """Valida o palpite. Com múltiplas tentativas, só trava no acerto."""
    if room.state != GameState.QUESTION or room.current_question is None:
        return
    if player.answered:  # já travado (acertou ou sem retry)
        return

    elapsed = time.monotonic() - (room.round_started_at or time.monotonic())
    correct = normalize(guess) in set(room.current_question.accepted_answers)

    if correct:
        player.last_correct = True
        player.answered = True
        player.score += compute_score(elapsed, room.round_duration)
    elif not room.allow_multiple_attempts:
        player.answered = True  # trava no erro quando sem retry

    locked = player.answered
    await manager.send_personal(player, {"type": "answer_result", "correct": correct, "locked": locked})

    # encerra o round cedo se todos acertaram
    if room.end_on_all_correct and all(p.last_correct for p in room.players.values()):
        room.round_skip = True
