"""Aquecimento do cache do Cloudinary.

O servidor dispara requisições às URLs derivadas (mp3 da pergunta, mp4 do reveal)
ANTES do cliente precisar delas, forçando o Cloudinary a transcodar e cachear no
edge. Quando o cliente pede a MESMA URL, é cache hit — sem transcode frio (o gargalo).
Como o servidor é quem aquece, nenhuma URL de resposta vaza para o cliente.
"""
from __future__ import annotations

import asyncio
import logging

import httpx

from app.media import cloudinary as cdn
from app.models.schemas import MediaType, Question

logger = logging.getLogger("ldkquiz.warm")

WARM_CONCURRENCY = 4       # fetches simultâneos (transcode no Cloudinary é paralelizável)
WARM_REQUEST_TIMEOUT = 40.0  # transcode frio pode demorar


def derived_urls(q: Question, audio_seconds: int) -> list[str]:
    """URLs do Cloudinary que o cliente vai pedir — exatamente as que aquecemos.
    O vídeo do reveal NÃO entra: é .webm cru servido direto pelo AnimeThemes (sem Cloudinary)."""
    if not q.media_url:
        return []
    if q.media_type == MediaType.VIDEO:
        # só o áudio da pergunta (f_mp3 do .ogg) passa pelo Cloudinary
        src = (q.metadata or {}).get("audio_url") or q.media_url
        return [cdn.question_audio_url(src, audio_seconds)]
    if q.media_type == MediaType.AUDIO:
        return [cdn.full_audio_url(q.media_url)]
    if q.media_type == MediaType.IMAGE:
        # aquecer o fetch base; os níveis pixelados são derivados baratos do mesmo source
        return [cdn.full_image_url(q.media_url)]
    return []


async def _warm_one(client: httpx.AsyncClient, url: str) -> None:
    try:
        # Range mínimo: dispara o transcode+cache no Cloudinary sem baixar tudo p/ o servidor.
        r = await client.get(url, headers={"Range": "bytes=0-1"})
        logger.debug("warm %s -> %s", r.status_code, url)
    except Exception as exc:  # rede/timeout — aquecimento é best-effort
        logger.debug("warm falhou (%s): %s", url, exc)


async def _warm_many(client: httpx.AsyncClient, urls: list[str]) -> None:
    sem = asyncio.Semaphore(WARM_CONCURRENCY)

    async def guarded(u: str) -> None:
        async with sem:
            await _warm_one(client, u)

    await asyncio.gather(*(guarded(u) for u in urls))


async def warm_deck(deck: list[Question], audio_seconds: int) -> None:
    """Aquece TODAS as questões do deck em background (roda como task paralela à partida)."""
    urls: list[str] = []
    for q in deck:
        urls.extend(derived_urls(q, audio_seconds))
    if not urls:
        return
    async with httpx.AsyncClient(timeout=WARM_REQUEST_TIMEOUT, follow_redirects=True) as client:
        await _warm_many(client, urls)
    logger.info("warm_deck: %d URLs aquecidas", len(urls))


async def ensure_warm(q: Question, audio_seconds: int, timeout: float) -> None:
    """Garante (com teto de tempo) que a mídia da questão imminente está quente.
    Se estourar o timeout, segue mesmo assim — o warm_deck continua em background."""
    urls = derived_urls(q, audio_seconds)
    if not urls:
        return
    try:
        async with httpx.AsyncClient(timeout=WARM_REQUEST_TIMEOUT, follow_redirects=True) as client:
            await asyncio.wait_for(_warm_many(client, urls), timeout=timeout)
    except Exception:  # noqa: BLE001 — best-effort; CancelledError (BaseException) ainda propaga
        logger.info("ensure_warm: seguindo sem aquecimento completo da questão")
