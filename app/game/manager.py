from __future__ import annotations

import logging

from fastapi import WebSocket

from app.game.state import SALAS, Player, Room

logger = logging.getLogger("ldkquiz.manager")


class ConnectionManager:
    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()

    def add_player(self, room: Room, player: Player) -> None:
        room.players[player.id] = player

    def remove_player(self, room: Room, player_id: str) -> None:
        """Remove o jogador; sala vazia → cancela loop e limpa do dict."""
        room.players.pop(player_id, None)
        if not room.players:
            if room.task and not room.task.done():
                room.task.cancel()
            SALAS.pop(room.code, None)
            logger.info("Sala %s removida (vazia)", room.code)

    async def send_personal(self, player: Player, message: dict) -> None:
        try:
            await player.ws.send_json(message)
        except Exception:  # conexão pode ter morrido entre um tick e outro
            logger.debug("Falha ao enviar para %s", player.id)

    async def broadcast(self, room: Room, message: dict) -> None:
        # cópia porque send_personal pode disparar remove_player durante a iteração
        for player in list(room.players.values()):
            await self.send_personal(player, message)


manager = ConnectionManager()
