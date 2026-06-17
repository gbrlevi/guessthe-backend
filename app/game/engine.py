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
from app.models.schemas import MediaType, Question

logger = logging.getLogger("ldkquiz.engine")

REVEAL_PAUSE = 4.0
STARTING_PAUSE = 2.0


def _media_payload(q: Question, level: int) -> dict:
    """Mídia parcial para o nível atual — sem resposta."""
    if q.media_type == MediaType.IMAGE and q.media_url:
        return {"kind": "image", "url": cdn.pixel_image_url(q.media_url, level)}
    if q.media_type == MediaType.AUDIO and q.media_url:
        return {"kind": "audio", "url": cdn.clip_audio_url(q.media_url, level + 1)}
    return {"kind": "text", "clues": q.clues[: level + 1]}


def _media_reveal(q: Question) -> dict:
    """Mídia completa — só chega aqui no REVEAL."""
    if q.media_type == MediaType.IMAGE and q.media_url:
        return {"kind": "image", "url": cdn.full_image_url(q.media_url)}
    if q.media_type == MediaType.AUDIO and q.media_url:
        return {"kind": "audio", "url": cdn.full_audio_url(q.media_url)}
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
        },
    }


def msg_question_start(room: Room) -> dict:
    q = room.current_question
    assert q is not None
    return {
        "type": "question_start",
        "round": room.current_round,
        "total_rounds": room.total_rounds,
        "category": q.category,
        "media_type": q.media_type.value,
        "duration": room.round_duration,
        "media": _media_payload(q, level=0),
    }


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

    room.state = GameState.QUESTION
    room.round_started_at = time.monotonic()
    await manager.broadcast(room, msg_question_start(room))

    duration = int(room.round_duration)
    for sec in range(duration):
        await asyncio.sleep(1)
        level = cdn.reveal_level_for(sec, room.round_duration)
        await manager.broadcast(room, msg_reveal_update(room, sec, level))

    room.state = GameState.REVEAL
    await manager.broadcast(room, msg_reveal_answer(room))
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
        await manager.broadcast(room, {"type": "game_starting", "total_rounds": room.total_rounds})
        await asyncio.sleep(STARTING_PAUSE)

        for idx, question in enumerate(room.deck):
            room.current_round = idx + 1
            room.current_question = question
            await run_round(room)
            await asyncio.sleep(REVEAL_PAUSE)

        room.state = GameState.FINISHED
        await manager.broadcast(room, msg_game_over(room))
    except asyncio.CancelledError:
        logger.info("Partida da sala %s cancelada", room.code)
        raise
    finally:
        room.current_question = None
        room.round_started_at = None
        room.task = None
        if room.state != GameState.FINISHED:
            room.state = GameState.LOBBY
        else:
            room.state = GameState.LOBBY
            room.current_round = 0


def start_game(room: Room, categories: list[str], total_rounds: int | None) -> bool:
    """Dispara a partida. Retorna False se já rolando."""
    if room.task and not room.task.done():
        return False
    room.categories = categories or []
    room.total_rounds = total_rounds or settings.default_total_rounds
    room.task = asyncio.create_task(run_game(room))
    return True


async def handle_answer(room: Room, player: Player, guess: str) -> None:
    """Valida o palpite — devolve só um booleano ao jogador."""
    if player.answered or room.state != GameState.QUESTION or room.current_question is None:
        return
    player.answered = True
    elapsed = time.monotonic() - (room.round_started_at or time.monotonic())
    correct = normalize(guess) in set(room.current_question.accepted_answers)
    player.last_correct = correct
    if correct:
        player.score += compute_score(elapsed, room.round_duration)
    await manager.send_personal(player, {"type": "answer_result", "correct": correct})
