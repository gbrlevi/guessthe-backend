from __future__ import annotations

from typing import Iterable

import httpx

from app.db.supabase_client import get_supabase
from app.game.scoring import normalize


def http_client() -> httpx.Client:
    return httpx.Client(timeout=30.0, headers={"User-Agent": "ldkquiz-seeder/0.1"})


def build_question(
    *,
    category: str,
    media_type: str,
    answer: str,
    media_url: str | None = None,
    clues: list[str] | None = None,
    ext_id: str | int | None = None,
    popularity: int = 0,
    aliases: Iterable[str] | None = None,
) -> dict:
    accepted = {normalize(answer)}
    for a in aliases or []:
        n = normalize(a)
        if n:
            accepted.add(n)
    accepted.discard("")
    return {
        "category": category,
        "media_type": media_type,
        "answer": answer,
        "accepted_answers": sorted(accepted),
        "media_url": media_url,
        "clues": clues or [],
        "metadata": {"ext_id": str(ext_id)} if ext_id is not None else {},
        "popularity": popularity,
    }


def replace_category(category: str, rows: list[dict], batch: int = 200) -> int:
    """Apaga a categoria e reinsere — re-rodar o seeder é seguro."""
    sb = get_supabase()
    sb.table("questions").delete().eq("category", category).execute()
    for i in range(0, len(rows), batch):
        chunk = rows[i : i + batch]
        if chunk:
            sb.table("questions").insert(chunk).execute()
    print(f"[{category}] {len(rows)} questões gravadas no Supabase.")
    return len(rows)
