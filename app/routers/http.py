"""REST: /health, /rooms, /categories, /singleplayer/question."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException

from app.data import questions as qdata
from app.game.state import SALAS, Room, generate_code
from app.media import cloudinary as cdn
from app.models.schemas import (
    CategoryInfo,
    CreateRoomRequest,
    CreateRoomResponse,
)

router = APIRouter()


@router.get("/health")
def health() -> dict:
    return {"status": "ok", "rooms": len(SALAS)}


@router.post("/rooms", response_model=CreateRoomResponse)
def create_room(req: CreateRoomRequest) -> CreateRoomResponse:
    """Cria sala e devolve code + host_id; host conecta via WS com esses dados."""
    code = generate_code()
    host_id = uuid.uuid4().hex
    SALAS[code] = Room(code=code, host_id=host_id)
    return CreateRoomResponse(code=code, host_id=host_id)


@router.get("/categories", response_model=list[CategoryInfo])
def categories() -> list[CategoryInfo]:
    return qdata.list_categories()


@router.get("/autocomplete", response_model=list[str])
def autocomplete(category: str, q: str) -> list[str]:
    if len(q) < 3:
        return []
    return qdata.autocomplete_answers(category, q)


@router.get("/singleplayer/question")
def singleplayer_question(category: str | None = None) -> dict:
    """1 questão pra testar pixelização — sem resposta nem URL original."""
    q = qdata.random_question([category] if category else None)
    if q is None:
        raise HTTPException(status_code=404, detail="Nenhuma questão encontrada.")
    return {
        "id": q.id,
        "category": q.category,
        "media_type": q.media_type.value,
        "media": (
            {"kind": "image", "url": cdn.pixel_image_url(q.media_url, 0)}
            if q.media_url
            else {"kind": "text", "clues": q.clues[:1]}
        ),
    }
