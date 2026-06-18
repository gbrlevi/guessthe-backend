"""Modelos Pydantic compartilhados (questões, payloads HTTP, contratos WS).

As mensagens WebSocket são montadas em `app/game/engine.py`; aqui ficam só os
tipos de dados e os payloads das rotas HTTP.
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


class MediaType(str, Enum):
    IMAGE = "image"
    AUDIO = "audio"
    VIDEO = "video"
    TEXT = "text"


class Question(BaseModel):
    """Uma questão vinda do Supabase. `answer`/`accepted_answers`/`media_url`
    NUNCA são enviados ao cliente antes da fase REVEAL."""

    id: str
    category: str
    media_type: MediaType
    answer: str
    accepted_answers: list[str] = Field(default_factory=list)
    media_url: str | None = None
    clues: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    popularity: int = 0


# ----- Payloads das rotas HTTP -----

class CreateRoomRequest(BaseModel):
    host_name: str = Field(min_length=1, max_length=24)


class CreateRoomResponse(BaseModel):
    code: str
    host_id: str


class CategoryInfo(BaseModel):
    category: str
    count: int


# ----- Tipos das mensagens WebSocket recebidas do cliente -----

class ClientMessage(BaseModel):
    type: Literal["join", "start_game", "submit_answer"]
    # join: name ; start_game: categories + total_rounds ; submit_answer: guess
    name: str | None = None
    guess: str | None = None
    categories: list[str] | None = None
    total_rounds: int | None = None
