"""FSM da partida + cronômetro assíncrono + builders das mensagens WS."""
from __future__ import annotations

import asyncio
import logging
import time

from app.config import settings
from app.data.questions import build_deck
from app.game.manager import manager
from app.game.scoring import compute_score, is_close_answer, normalize
from app.game.state import GameState, Player, Room
from app.media import cloudinary as cdn
from app.media import warm
from app.models.schemas import MediaType, Question
from app.routers.media import register_audio, register_media

logger = logging.getLogger("ldkquiz.engine")

REVEAL_PAUSE = 4.0
VIDEO_REVEAL_PAUSE = 6.0
STARTING_PAUSE = 2.0

# Modo Tensão: as últimas 30% das rodadas valem PONTUAÇÃO DOBRADA. Antes da
# primeira delas o servidor envia `tension_intro` e segura o próximo round por
# TENSION_INTERSTITIAL s (assim o cronômetro do round só começa depois do overlay
# do cliente — o jogador não perde tempo de palpite com a "calmaria").
TENSION_RATIO = 0.7
TENSION_INTERSTITIAL = 5.0
TENSION_MULTIPLIER = 2


def _is_tension_round(round_num: int, total: int, ratio: float = TENSION_RATIO) -> bool:
    return total > 0 and round_num > total * ratio

AUDIO_BUFFER_SECONDS = 5   # áudio servido = duração do round + folga
WARM_AWAIT_TIMEOUT = 10.0  # teto p/ aquecer a questão imminente antes de começar

MIN_GUESS_INTERVAL = 0.35  # s entre palpites do mesmo jogador (anti-flood do feed)


def _audio_seconds(room: Room) -> int:
    return int(room.round_duration) + AUDIO_BUFFER_SECONDS


def _video_audio_source(q: Question) -> str | None:
    """Fonte de áudio p/ questões de vídeo: o .ogg separado (pequeno, transcoda no
    Cloudinary) em vez do .webm gigante. Fallback: o próprio .webm (legado/sem ogg)."""
    return (q.metadata or {}).get("audio_url") or q.media_url


def _media_payload(q: Question, level: int) -> dict:
    """Mídia para o round. Imagens são progressivas (level); áudio/vídeo vêm por URL opaca."""
    if q.media_type == MediaType.IMAGE and q.media_url:
        return {"kind": "image", "url": cdn.pixel_image_url(q.media_url, level)}
    # URL opaca: nunca envia o caminho Cloudinary/AnimeThemes que contém o nome da resposta.
    if q.media_type in (MediaType.AUDIO, MediaType.VIDEO) and q.media_url:
        return {"kind": "audio", "url": _audio_proxy_path(q)}
    return {"kind": "text", "clues": q.clues[: level + 1]}


def _media_reveal(q: Question) -> dict:
    """Mídia completa — só chega aqui no REVEAL."""
    if q.media_type == MediaType.IMAGE and q.media_url:
        return {"kind": "image", "url": cdn.full_image_url(q.media_url)}
    if q.media_type == MediaType.AUDIO and q.media_url:
        return {"kind": "audio", "url": _audio_proxy_path(q)}
    if q.media_type == MediaType.VIDEO and q.media_url:
        # URL opaca via proxy (não vaza o nome do anime); o cliente já pré-buscou no palpite.
        return {"kind": "video", "url": _video_proxy_path(q)}
    return {"kind": "text", "clues": q.clues}


def _video_proxy_path(q: Question) -> str:
    return f"/media/video/{q.id}"


def _audio_proxy_path(q: Question) -> str:
    return f"/media/audio/{q.id}"


def _players_public(room: Room) -> list[dict]:
    return [
        {"id": p.id, "name": p.name, "score": p.score, "is_host": p.is_host, "avatar": p.avatar}
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
            "depixel_speed": room.depixel_speed,
            "tension_enabled": room.tension_enabled,
            "tension_ratio": room.tension_ratio,
        },
    }


def msg_round_paused(room: Room) -> dict:
    return {"type": "round_paused", "time_left": max(0, int(room.round_duration) - room.current_round)}


def msg_round_resumed() -> dict:
    return {"type": "round_resumed"}


def msg_question_start(room: Room) -> dict:
    q = room.current_question
    assert q is not None
    # Nenhuma URL de resposta vaza aqui: VIDEO só manda o áudio (a pergunta).
    msg: dict = {
        "type": "question_start",
        "round": room.current_round,
        "total_rounds": room.total_rounds,
        "category": q.category,
        "media_type": q.media_type.value,
        "duration": room.round_duration,
        "media": _media_payload(q, 0),
    }
    # Pré-busca do vídeo do reveal via URL OPACA (sem o nome do anime). O cliente
    # baixa durante o palpite; no reveal usa a mesma URL → cache hit → sem delay.
    if q.media_type == MediaType.VIDEO and q.media_url:
        msg["prefetch_url"] = _video_proxy_path(q)
    return msg


def msg_reveal_update(room: Room, elapsed_sec: int, level: int) -> dict:
    q = room.current_question
    assert q is not None
    time_left = max(0, int(room.round_duration) - (elapsed_sec + 1))
    return {
        "type": "reveal_update",
        "level": level,
        "time_left": time_left,
        "media": _media_payload(q, level),
    }


def msg_reveal_answer(room: Room) -> dict:
    q = room.current_question
    assert q is not None
    return {
        "type": "reveal_answer",
        "answer": q.answer,
        "media": _media_reveal(q),
        "results": [
            {"id": p.id, "name": p.name, "correct": p.last_correct, "score": p.score, "avatar": p.avatar}
            for p in room.players.values()
        ],
    }


def msg_scoreboard(room: Room) -> dict:
    ranking = sorted(room.players.values(), key=lambda p: p.score, reverse=True)
    return {
        "type": "scoreboard",
        "round": room.current_round,
        "total_rounds": room.total_rounds,
        "ranking": [{"id": p.id, "name": p.name, "score": p.score, "avatar": p.avatar} for p in ranking],
    }


def msg_tension_intro(room: Room, interstitial_ms: int) -> dict:
    """Interstício do Modo Tensão (antes da 1ª rodada dos últimos 30%)."""
    ranking = sorted(room.players.values(), key=lambda p: p.score, reverse=True)
    return {
        "type": "tension_intro",
        "round": room.current_round,
        "total_rounds": room.total_rounds,
        "interstitial_ms": interstitial_ms,
        "ranking": [
            {"id": p.id, "name": p.name, "score": p.score, "avatar": p.avatar}
            for p in ranking[:3]
        ],
    }


def msg_game_over(room: Room) -> dict:
    ranking = sorted(room.players.values(), key=lambda p: p.score, reverse=True)
    return {
        "type": "game_over",
        "ranking": [{"id": p.id, "name": p.name, "score": p.score, "avatar": p.avatar} for p in ranking],
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

        level = cdn.reveal_level_for(sec, room.round_duration, room.depixel_speed)
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
        room.deck = await asyncio.to_thread(build_deck, room.categories, room.total_rounds)
        if not room.deck:
            await manager.broadcast(room, {"type": "error", "message": "Sem questões para as categorias escolhidas."})
            room.state = GameState.LOBBY
            await manager.broadcast(room, msg_lobby_update(room))
            return

        room.total_rounds = len(room.deck)

        # Registra os tokens opacos de vídeo e áudio (UUID → URL real).
        # O cliente nunca vê URLs com o nome do anime — só os UUIDs opacos.
        audio_secs = _audio_seconds(room)
        for q in room.deck:
            if q.media_type == MediaType.VIDEO and q.media_url:
                register_media(q.id, q.media_url)
                register_audio(q.id, cdn.question_audio_url(_video_audio_source(q), audio_secs))
            elif q.media_type == MediaType.AUDIO and q.media_url:
                register_audio(q.id, cdn.full_audio_url(q.media_url))

        # Aquece o cache do Cloudinary p/ TODO o deck em background.
        room.warm_task = asyncio.create_task(warm.warm_deck(room.deck, audio_secs))

        await manager.broadcast(room, {"type": "game_starting", "total_rounds": room.total_rounds})
        await asyncio.sleep(STARTING_PAUSE)

        for idx, question in enumerate(room.deck):
            room.current_round = idx + 1
            room.current_question = question

            # Calmaria antes da tempestade: na PRIMEIRA rodada de tensão (e desde
            # que tenha havido ao menos uma rodada normal antes), avisa os clientes
            # e segura o início — o cronômetro do round só corre após o overlay.
            if (
                room.tension_enabled
                and room.current_round > 1
                and _is_tension_round(room.current_round, room.total_rounds, room.tension_ratio)
                and not _is_tension_round(room.current_round - 1, room.total_rounds, room.tension_ratio)
            ):
                await manager.broadcast(room, msg_tension_intro(room, int(TENSION_INTERSTITIAL * 1000)))
                await asyncio.sleep(TENSION_INTERSTITIAL)

            await run_round(room)
            await asyncio.sleep(STARTING_PAUSE)  # pausa entre scoreboard e próximo round

        room.state = GameState.FINISHED
        await manager.broadcast(room, msg_game_over(room))
    except asyncio.CancelledError:
        logger.info("Partida da sala %s cancelada", room.code)
        raise
    except Exception as exc:
        logger.exception("Partida da sala %s encerrou com erro inesperado: %s", room.code, exc)
        try:
            await manager.broadcast(room, {"type": "error", "message": "Erro interno — a partida foi encerrada."})
        except Exception:
            pass
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
    depixel_speed: int | None = None,
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
    if depixel_speed is not None:
        room.depixel_speed = max(1, min(10, int(depixel_speed)))
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


def promote_new_host(room: Room) -> Player | None:
    """Elege um novo host quando o atual desconecta (host órfão).

    O primeiro jogador restante vira host: garante que o lobby/partida volte a ter
    quem controla pausa/início. Atualiza `room.host_id` para refletir o novo dono.
    Retorna o novo host (ou None se a sala ficou vazia)."""
    if not room.players:
        return None
    new_host = next(iter(room.players.values()))
    for p in room.players.values():
        p.is_host = p.id == new_host.id
    room.host_id = new_host.id
    logger.info("Sala %s: host reatribuído para %s", room.code, new_host.name)
    return new_host


async def handle_answer(room: Room, player: Player, guess: str) -> None:
    """Valida o palpite. Com múltiplas tentativas, só trava no acerto."""
    if room.state != GameState.QUESTION or room.current_question is None:
        return
    if player.answered:  # já travado (acertou ou sem retry)
        return

    now = time.monotonic()
    # Anti-spam: ignora silenciosamente palpites em rajada do mesmo jogador.
    if now - player.last_guess_at < MIN_GUESS_INTERVAL:
        return
    player.last_guess_at = now

    elapsed = now - (room.round_started_at or now)
    correct = normalize(guess) in set(room.current_question.accepted_answers)

    if correct:
        player.last_correct = True
        player.answered = True
        # Rodadas finais valem em dobro (Modo Tensão).
        multiplier = (
            TENSION_MULTIPLIER
            if room.tension_enabled and _is_tension_round(room.current_round, room.total_rounds, room.tension_ratio)
            else 1
        )
        player.score += compute_score(elapsed, room.round_duration) * multiplier
    elif not room.allow_multiple_attempts:
        player.answered = True  # trava no erro quando sem retry

    locked = player.answered
    await manager.send_personal(player, {"type": "answer_result", "correct": correct, "locked": locked})

    # Notifica apenas o jogador que seu palpite estava próximo (similar ao Gartic).
    if not correct and is_close_answer(guess, room.current_question.accepted_answers):
        await manager.send_personal(player, {"type": "close_answer"})

    # Broadcast do palpite no chat para todos os jogadores.
    # Palpites errados aparecem com o texto; acertos escondem a resposta.
    await manager.broadcast(room, {
        "type": "chat_message",
        "player_id": player.id,
        "player_name": player.name,
        "avatar": player.avatar,
        "msg_type": "correct" if correct else "guess",
        "text": "" if correct else guess,
    })

    # encerra o round cedo se todos acertaram
    if room.end_on_all_correct and all(p.last_correct for p in room.players.values()):
        room.round_skip = True
