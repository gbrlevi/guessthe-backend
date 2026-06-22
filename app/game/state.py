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


class GameMode(str, Enum):
    QUIZ = "quiz"
    TERMO = "termo"
    MISTO = "misto"  # quiz + termo intercalados na mesma partida


class TermoMode(str, Enum):
    PVP_INDIVIDUAL = "pvp_individual"
    TABULEIRO_COMPARTILHADO = "tabuleiro_compartilhado"


@dataclass
class TermoSubmission:
    """Uma linha do tabuleiro (palpite + cores resultantes)."""
    player_id: str
    player_name: str
    avatar: str
    letters: list[str]
    colors: list[str]  # "correct" | "present" | "absent" por posição
    at: float          # monotonic


@dataclass
class TermoPlayerState:
    """Estado por jogador, por rodada (usado no PVP_INDIVIDUAL)."""
    attempts: list[TermoSubmission] = field(default_factory=list)
    solved: bool = False
    solved_at: float | None = None


@dataclass
class TermoRoundState:
    """Estado da rodada de Termo. Reconstruído a cada rodada e guardado em Room.

    `word`/`hint` são SEGREDO: nunca serializados antes do REVEAL (a dica só após
    `termo_hint_delay`)."""
    word: str          # MAIÚSCULA, sem acentos — nunca sai antes do REVEAL
    length: int
    theme: str
    hint: str          # segredo até termo_hint_delay
    hint_sent: bool = False
    max_attempts: int = 6
    # Tabuleiro compartilhado
    shared_grid: list[TermoSubmission] = field(default_factory=list)
    discovered_correct: set[int] = field(default_factory=set)   # posições verdes (global)
    discovered_present: set[str] = field(default_factory=set)   # letras amarelas (global)
    solved_by: str | None = None
    # Por jogador (PVP)
    players: dict[str, TermoPlayerState] = field(default_factory=dict)


@dataclass
class Player:
    id: str
    name: str
    ws: "WebSocket"
    avatar: str = "fox"
    score: int = 0
    answered: bool = False
    last_correct: bool = False
    is_host: bool = False
    last_guess_at: float = 0.0  # monotonic do último palpite (anti-spam)


@dataclass
class Room:
    code: str
    host_id: str
    name: str = ""
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
    depixel_speed: int = 5  # 1 (lento) a 10 (rápido) — controlado pelo host
    tension_enabled: bool = True
    tension_ratio: float = 0.7  # fração do total acima da qual as rodadas são de tensão (ex.: 0.7 = últimos 30%)
    paused: bool = False
    round_skip: bool = False  # sinaliza fim antecipado do round

    # --- Modo Termo (segundo modo de jogo) ---
    game_mode: GameMode = GameMode.QUIZ
    termo_mode: TermoMode = TermoMode.PVP_INDIVIDUAL
    termo_round_duration: float = 60.0  # campo dedicado (round_duration carrega semântica de quiz/depixel)
    submission_cooldown: float = 2.0    # 0..5s entre palpites (visível ao jogador)
    termo_hint_delay: float = 30.0      # s até revelar a dica no meio da rodada
    mixed_termo_ratio: float = 0.5      # no modo MISTO: fração das rodadas que são de Termo (0..1)
    cooldown_tracker: dict[str, float] = field(default_factory=dict)  # player_id → monotonic do último palpite
    termo_round: "TermoRoundState | None" = None

    task: "asyncio.Task | None" = None  # cancelável quando a sala esvazia
    warm_task: "asyncio.Task | None" = None  # aquecimento de cache em background


SALAS: dict[str, Room] = {}


def generate_code(length: int = 4) -> str:
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # sem I/O/0/1 pra não confundir
    while True:
        code = "".join(random.choices(alphabet, k=length))
        if code not in SALAS:
            return code
