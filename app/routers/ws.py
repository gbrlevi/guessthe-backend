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


@router.websocket("/ws/{room_code}")
async def ws_endpoint(ws: WebSocket, room_code: str, name: str, player_id: str | None = None):
    room = SALAS.get(room_code.upper())
    if room is None:
        await ws.accept()
        await ws.send_json({"type": "error", "message": "Sala não encontrada."})
        await ws.close(code=4404)
        return

    await manager.connect(ws)

    is_host = player_id is not None and player_id == room.host_id
    pid = room.host_id if is_host else uuid.uuid4().hex
    player = Player(id=pid, name=name[:24] or "Jogador", ws=ws, is_host=is_host)
    manager.add_player(room, player)
    await manager.broadcast(room, engine.msg_lobby_update(room))
    logger.info("%s entrou na sala %s (host=%s)", player.name, room.code, is_host)

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
                ok = engine.start_game(room, msg.categories or [], msg.total_rounds)
                if not ok:
                    await manager.send_personal(player, {"type": "error", "message": "Partida já em andamento."})

            elif msg.type == "join":
                # re-anuncia lobby (útil em reconexão)
                if msg.name:
                    player.name = msg.name[:24]
                await manager.broadcast(room, engine.msg_lobby_update(room))

    except WebSocketDisconnect:
        manager.remove_player(room, player.id)
        if room.code in SALAS:
            await manager.broadcast(room, engine.msg_lobby_update(room))
        logger.info("%s saiu da sala %s", player.name, room.code)
