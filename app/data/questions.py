from __future__ import annotations

import random

from app.db.supabase_client import get_supabase
from app.models.schemas import CategoryInfo, Question

POOL_SIZE = 300


def _to_question(row: dict) -> Question:
    return Question(
        id=str(row["id"]),
        category=row["category"],
        media_type=row["media_type"],
        answer=row["answer"],
        accepted_answers=row.get("accepted_answers") or [],
        media_url=row.get("media_url"),
        clues=row.get("clues") or [],
        metadata=row.get("metadata") or {},
        popularity=row.get("popularity") or 0,
    )


def list_categories() -> list[CategoryInfo]:
    sb = get_supabase()
    rows = sb.rpc("category_counts", {}).execute().data or []
    return [CategoryInfo(category=r["category"], count=r["count"]) for r in rows]


def fetch_pool(categories: list[str]) -> list[Question]:
    sb = get_supabase()
    query = sb.table("questions").select("*")
    if categories:
        query = query.in_("category", categories)
    res = query.order("popularity", desc=True).limit(POOL_SIZE).execute()
    return [_to_question(r) for r in (res.data or [])]


def build_deck(categories: list[str], total_rounds: int) -> list[Question]:
    """Embaralha o pool e retorna N questões; repete se o pool for menor que N."""
    pool = fetch_pool(categories)
    random.shuffle(pool)
    if len(pool) >= total_rounds:
        return pool[:total_rounds]
    deck = list(pool)
    while len(deck) < total_rounds and pool:
        deck.append(random.choice(pool))
    return deck


def random_question(categories: list[str] | None = None) -> Question | None:
    pool = fetch_pool(categories or [])
    return random.choice(pool) if pool else None
