"""FSM do modo Termo (paralela ao quiz). `engine.run_game` delega aqui quando
`room.game_mode == TERMO`. Reaproveita pausa/skip/broadcast e os builders
genéricos de `engine` (scoreboard/game_over/lobby), mas é text-only — sem
warming de mídia nem tokens opacos."""
from __future__ import annotations

import asyncio
import logging
import time

from app.data.questions import build_termo_deck
from app.game import engine, termo
from app.game.manager import manager
from app.game.state import (
    GameState,
    Player,
    Room,
    TermoMode,
    TermoPlayerState,
    TermoRoundState,
    TermoSubmission,
)

logger = logging.getLogger("ldkquiz.termo")


async def run_termo_round(room: Room) -> None:
    q = room.current_question
    assert q is not None

    word = termo.fold_upper(q.answer)
    theme = (q.metadata or {}).get("theme") or q.category
    hint = q.clues[0] if q.clues else ""
    max_attempts = int((q.metadata or {}).get("max_attempts") or 6)

    tr = TermoRoundState(
        word=word, length=len(word), theme=theme, hint=hint, max_attempts=max_attempts
    )
    room.termo_round = tr
    room.cooldown_tracker.clear()
    for p in room.players.values():
        p.answered = False
        p.last_correct = False
        tr.players[p.id] = TermoPlayerState()

    room.paused = False
    room.round_skip = False
    room.state = GameState.QUESTION
    room.round_started_at = time.monotonic()
    await manager.broadcast(room, termo.msg_termo_question_start(room))  # SEM a palavra

    duration = int(room.termo_round_duration)
    hint_at = int(room.termo_hint_delay)
    for sec in range(duration):
        while room.paused:
            await asyncio.sleep(0.2)
        await asyncio.sleep(1)
        if room.round_skip:
            break
        if not tr.hint_sent and tr.hint and (sec + 1) >= hint_at:
            tr.hint_sent = True
            await manager.broadcast(room, termo.msg_termo_hint(tr))

    room.state = GameState.REVEAL
    await manager.broadcast(room, termo.msg_termo_reveal(room))  # palavra/dica saem AQUI
    await asyncio.sleep(engine.REVEAL_PAUSE)

    room.state = GameState.SCOREBOARD
    await manager.broadcast(room, engine.msg_scoreboard(room))


async def run_termo_game(room: Room) -> None:
    """STARTING → N rodadas de Termo → FINISHED. Roda como room.task."""
    try:
        for p in room.players.values():
            p.score = 0

        room.state = GameState.STARTING
        room.deck = await asyncio.to_thread(build_termo_deck, room.categories, room.total_rounds)
        if not room.deck:
            await manager.broadcast(
                room, {"type": "error", "message": "Sem palavras para as categorias escolhidas."}
            )
            room.state = GameState.LOBBY
            await manager.broadcast(room, engine.msg_lobby_update(room))
            return

        room.total_rounds = len(room.deck)

        await manager.broadcast(room, {"type": "game_starting", "total_rounds": room.total_rounds})
        await asyncio.sleep(engine.STARTING_PAUSE)

        for idx, question in enumerate(room.deck):
            room.current_round = idx + 1
            room.current_question = question
            await run_termo_round(room)
            await asyncio.sleep(engine.STARTING_PAUSE)

        room.state = GameState.FINISHED
        await manager.broadcast(room, engine.msg_game_over(room))
    except asyncio.CancelledError:
        logger.info("Partida Termo da sala %s cancelada", room.code)
        raise
    except Exception as exc:
        logger.exception("Partida Termo da sala %s encerrou com erro: %s", room.code, exc)
        try:
            await manager.broadcast(room, {"type": "error", "message": "Erro interno — a partida foi encerrada."})
        except Exception:
            pass
    finally:
        room.termo_round = None
        room.cooldown_tracker.clear()
        room.current_question = None
        room.round_started_at = None
        room.task = None
        if room.state == GameState.FINISHED:
            room.current_round = 0
        room.state = GameState.LOBBY


async def handle_guess(room: Room, player: Player, guess: str) -> None:
    """Processa um palpite de Termo. Cooldown é checado ANTES da validação."""
    if room.state != GameState.QUESTION or room.termo_round is None:
        return
    tr = room.termo_round
    now = time.monotonic()

    # --- Middleware de cooldown (validação temporal) ---
    cd = room.submission_cooldown
    if cd > 0:
        last = room.cooldown_tracker.get(player.id)
        if last is not None and now - last < cd:
            await manager.send_personal(player, termo.msg_cooldown_error(cd - (now - last)))
            return
    room.cooldown_tracker[player.id] = now

    # --- Validação de formato (tamanho + apenas letras) ---
    g = termo.validate_guess_shape(guess, tr.length)
    if g is None:
        await manager.send_personal(player, termo.msg_guess_error("length", tr.length))
        return

    ps = tr.players.get(player.id)
    if ps is None:  # entrou no meio da rodada
        ps = TermoPlayerState()
        tr.players[player.id] = ps

    if room.termo_mode == TermoMode.PVP_INDIVIDUAL:
        if ps.solved:
            return
        if len(ps.attempts) >= tr.max_attempts:
            await manager.send_personal(player, termo.msg_guess_error("exhausted"))
            return

        colors = termo.color_guess(g, tr.word)
        ps.attempts.append(TermoSubmission(player.id, player.name, player.avatar, list(g), colors, now))
        solved = termo.is_solved(colors)
        attempts_left = tr.max_attempts - len(ps.attempts)

        if solved:
            is_first = not any(s.solved for s in tr.players.values())
            ps.solved = True
            ps.solved_at = now
            player.last_correct = True
            player.answered = True
            elapsed = now - (room.round_started_at or now)
            player.score += termo.score_pvp_solve(elapsed, room.termo_round_duration, attempts_left, is_first)

        # Resultado completo só para o autor; progresso CENSURADO para a sala.
        await manager.send_personal(
            player, termo.msg_guess_result(list(g), colors, len(ps.attempts) - 1, attempts_left, solved)
        )
        await manager.broadcast(room, termo.msg_opponent_progress(player, colors, attempts_left, solved))

        # Encerra cedo quando todos os presentes resolveram ou esgotaram tentativas.
        if all(
            (tr.players.get(p.id) is not None
             and (tr.players[p.id].solved or len(tr.players[p.id].attempts) >= tr.max_attempts))
            for p in room.players.values()
        ):
            room.round_skip = True
        return

    # --- TABULEIRO_COMPARTILHADO ---
    if tr.solved_by is not None:
        await manager.send_personal(player, termo.msg_guess_error("closed"))
        return

    colors = termo.color_guess(g, tr.word)
    sub = TermoSubmission(player.id, player.name, player.avatar, list(g), colors, now)
    tr.shared_grid.append(sub)
    solved = termo.is_solved(colors)

    if solved:
        # asyncio single-thread: não há await entre o check de solved_by e esta
        # atribuição, então o primeiro a 100% vence atomicamente.
        tr.solved_by = player.id
        player.last_correct = True
        player.answered = True
        delta = termo.FULL_SOLVE_POINTS
        player.score += delta
    else:
        delta = termo.score_shared_guess(tr, colors, g)
        player.score += delta

    await manager.broadcast(room, termo.msg_shared_grid_update(sub, delta))  # palpite ABERTO
    await manager.send_personal(
        player, termo.msg_guess_result(list(g), colors, len(tr.shared_grid) - 1, None, solved)
    )
    if solved:
        await manager.broadcast(room, termo.msg_termo_solved(player))
        room.round_skip = True
