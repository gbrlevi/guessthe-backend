from __future__ import annotations

from typing import Iterable

import httpx

from app.db.supabase_client import get_supabase
from app.game.scoring import normalize


def http_client() -> httpx.Client:
    return httpx.Client(timeout=30.0, headers={"User-Agent": "ldkquiz-seeder/0.1"})


def pick_smallest_webm(videos: list[dict]) -> dict | None:
    """Menor variante .webm (por tamanho; fallback resolução). O Cloudinary só transcoda
    fontes pequenas on-the-fly — e o browser baixa menos bytes via Range. None se não houver."""
    webms = [v for v in videos if (v.get("link") or "").endswith(".webm")]
    if not webms:
        return None
    return min(webms, key=lambda v: (v.get("size") or 10**15, v.get("resolution") or 9999))


def audio_link_from(videos: list[dict]) -> str | None:
    """Primeiro link de áudio (.ogg) entre as variantes — pequeno, usado na fase de pergunta."""
    for v in videos:
        link = (v.get("audio") or {}).get("link")
        if link:
            return link
    return None


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
    audio_url: str | None = None,
) -> dict:
    accepted = {normalize(answer)}
    for a in aliases or []:
        n = normalize(a)
        if n:
            accepted.add(n)
    accepted.discard("")
    metadata: dict = {}
    if ext_id is not None:
        metadata["ext_id"] = str(ext_id)
    if audio_url:  # áudio separado (ex.: .ogg do AnimeThemes) p/ a fase de pergunta
        metadata["audio_url"] = audio_url
    return {
        "category": category,
        "media_type": media_type,
        "answer": answer,
        "accepted_answers": sorted(accepted),
        "media_url": media_url,
        "clues": clues or [],
        "metadata": metadata,
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
