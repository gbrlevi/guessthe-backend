"""Estado global em RAM. 1 worker só — múltiplos processos fragmentam SALAS."""
from __future__ import annotations

import asyncio
import random
import string
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

from app.config import settings

if TYPE_CHECKING: 
    from fastapi import WebSocket

    from app.models.schemas import Question


class GameState(str, Enum):
    LOBBY = "lobby"
    STARTING = "starting"
    QUESTION = "question"
    REVEAL = "reveal"
    SCOREBOARD = "scoreboard"
    FINISHED = "finished"


@dataclass
class Player:
    id: str
    name: str
    ws: "WebSocket"
    score: int = 0
    answered: bool = False
    last_correct: bool = False
    is_host: bool = False


@dataclass
class Room:
    code: str
    host_id: str
    players: dict[str, Player] = field(default_factory=dict)
    state: GameState = GameState.LOBBY
    categories: list[str] = field(default_factory=list)
    total_rounds: int = settings.default_total_rounds
    round_duration: float = settings.default_round_duration

    current_round: int = 0
    deck: list["Question"] = field(default_factory=list)
    current_question: "Question | None" = None
    round_started_at: float | None = None

    allow_multiple_attempts: bool = True
    end_on_all_correct: bool = True
    paused: bool = False
    round_skip: bool = False  # sinaliza fim antecipado do round

    task: "asyncio.Task | None" = None  # cancelável quando a sala esvazia
    warm_task: "asyncio.Task | None" = None  # aquecimento de cache em background


SALAS: dict[str, Room] = {}


def generate_code(length: int = 4) -> str:
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # sem I/O/0/1 pra não confundir
    while True:
        code = "".join(random.choices(alphabet, k=length))
        if code not in SALAS:
            return code
