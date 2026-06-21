"""WS /ws/{room_code}?name=...&player_id=... — player_id == host_id → entra como host."""
from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from app.game import engine
from app.game.manager import manager
from app.game.state import SALAS, GameState, Player
from app.models.schemas import ClientMessage

logger = logging.getLogger("ldkquiz.ws")
router = APIRouter()


VALID_AVATARS = {"fox","frog","panda","unicorn","octopus","dragon","lion","penguin","whale","alien","robot","wolf"}


@router.websocket("/ws/{room_code}")
async def ws_endpoint(ws: WebSocket, room_code: str, name: str, player_id: str | None = None, avatar: str | None = None):
    room = SALAS.get(room_code.upper())
    if room is None:
        await ws.accept()
        await ws.send_json({"type": "error", "message": "Sala não encontrada."})
        await ws.close(code=4404)
        return

    await manager.connect(ws)

    safe_avatar = avatar if avatar in VALID_AVATARS else "fox"
    is_host = player_id is not None and player_id == room.host_id
    pid = room.host_id if is_host else uuid.uuid4().hex
    player = Player(id=pid, name=name[:24] or "Jogador", ws=ws, is_host=is_host, avatar=safe_avatar)
    manager.add_player(room, player)
    # Informa ao cliente o seu PRÓPRIO id — habilita isHost autoritativo no servidor
    # e a reatribuição de host (o cliente compara seu id ao host_id do lobby_update).
    await manager.send_personal(player, {"type": "joined", "player_id": player.id})
    await manager.broadcast(room, engine.msg_lobby_update(room))
    logger.info("%s entrou na sala %s (host=%s, avatar=%s)", player.name, room.code, is_host, safe_avatar)

    try:
        while True:
            raw = await ws.receive_json()
            try:
                msg = ClientMessage(**raw)
            except ValidationError:
                await manager.send_personal(player, {"type": "error", "message": "Mensagem inválida."})
                continue

            if msg.type == "submit_answer":
                await engine.handle_answer(room, player, msg.guess or "")

            elif msg.type == "start_game":
                if not player.is_host:
                    await manager.send_personal(player, {"type": "error", "message": "Apenas o host inicia."})
                    continue
                if room.state not in (GameState.LOBBY, GameState.FINISHED):
                    continue
                ok = engine.start_game(
                    room,
                    msg.categories or [],
                    msg.total_rounds,
                    msg.round_duration,
                    msg.allow_multiple_attempts,
                    msg.end_on_all_correct,
                    msg.depixel_speed,
                )
                if not ok:
                    await manager.send_personal(player, {"type": "error", "message": "Partida já em andamento."})

            elif msg.type == "pause_round":
                if player.is_host:
                    await engine.handle_pause(room)

            elif msg.type == "resume_round":
                if player.is_host:
                    await engine.handle_resume(room)

            elif msg.type == "update_settings":
                # Host atualiza configurações em tempo real antes de iniciar o jogo
                if not player.is_host:
                    continue
                if room.state not in (GameState.LOBBY, GameState.FINISHED):
                    continue
                if msg.categories is not None:
                    room.categories = msg.categories
                if msg.total_rounds is not None:
                    room.total_rounds = max(1, min(50, msg.total_rounds))
                if msg.round_duration is not None:
                    room.round_duration = max(5.0, min(120.0, msg.round_duration))
                if msg.allow_multiple_attempts is not None:
                    room.allow_multiple_attempts = msg.allow_multiple_attempts
                if msg.end_on_all_correct is not None:
                    room.end_on_all_correct = msg.end_on_all_correct
                if msg.depixel_speed is not None:
                    room.depixel_speed = max(1, min(10, msg.depixel_speed))
                if msg.tension_enabled is not None:
                    room.tension_enabled = msg.tension_enabled
                if msg.tension_ratio is not None:
                    room.tension_ratio = max(0.1, min(0.95, msg.tension_ratio))
                await manager.broadcast(room, engine.msg_lobby_update(room))

            elif msg.type == "join":
                # re-anuncia lobby (útil em reconexão)
                if msg.name:
                    player.name = msg.name[:24]
                if msg.avatar and msg.avatar in VALID_AVATARS:
                    player.avatar = msg.avatar
                await manager.broadcast(room, engine.msg_lobby_update(room))

    except WebSocketDisconnect:
        was_host = player.is_host
        manager.remove_player(room, player.id)
        if room.code in SALAS:
            # Host órfão: se quem saiu era o host e ainda há gente, elege um novo.
            if was_host and room.players:
                engine.promote_new_host(room)
            await manager.broadcast(room, engine.msg_lobby_update(room))
        logger.info("%s saiu da sala %s", player.name, room.code)
