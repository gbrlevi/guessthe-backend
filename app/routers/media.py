"""Proxy de mídia com URLs opacas (anti-cheat).
Qualquer URL enviada ao cliente durante a fase de palpite — incluindo URLs Cloudinary que embutem a
origem URL-encoded — vazaria a resposta. O proxy resolve ao usar apenas o UUID
da questão (opaco) em tudo que o cliente recebe.

/media/video/{token} — stream do .webm via Range/206 (teto de 8 MB)
/media/audio/{token} — áudio buffered (mp3/ogg, arquivo pequeno, sem Range)
"""
from __future__ import annotations

import logging

import httpx
from fastapi import APIRouter, Header
from fastapi.responses import Response, StreamingResponse

logger = logging.getLogger("ldkquiz.media")

router = APIRouter()

http_client = httpx.AsyncClient(
    timeout=httpx.Timeout(60.0, connect=10.0),
    follow_redirects=True,
    limits=httpx.Limits(max_connections=100, max_keepalive_connections=20)
)


@router.on_event("shutdown")
async def shutdown_event():
    await http_client.aclose()


# token (UUID da questão) -> URL real do .webm. Populado pela engine no início da partida.
MEDIA_TOKENS: dict[str, str] = {}
_SIZES: dict[str, int] = {}  # cache do tamanho real (bytes) por token

# token (UUID da questão) -> URL de áudio (Cloudinary mp3 ou .ogg direto)
AUDIO_TOKENS: dict[str, str] = {}

# Reveal dura ~6s; ~0,5 MB/s de bitrate → poucos MB cobrem o trecho exibido.
MAX_BYTES = 8 * 1024 * 1024
CHUNK = 64 * 1024
# headers de navegador (o AnimeThemes serve 206 a qualquer um, mas mantemos consistência)
_UPSTREAM = {"User-Agent": "Mozilla/5.0", "Referer": "https://animethemes.moe/"}


def register_media(token: str, url: str) -> None:
    MEDIA_TOKENS[token] = url


def register_audio(token: str, url: str) -> None:
    AUDIO_TOKENS[token] = url


async def _real_total(client: httpx.AsyncClient, url: str, token: str) -> int:
    """Tamanho real do arquivo upstream (cacheado por token)."""
    if token in _SIZES:
        return _SIZES[token]
    r = await client.get(url, headers={**_UPSTREAM, "Range": "bytes=0-0"})
    total = MAX_BYTES
    cr = r.headers.get("content-range", "")
    if "/" in cr:
        try:
            total = int(cr.rsplit("/", 1)[1])
        except ValueError:
            pass
    _SIZES[token] = total
    return total


def _parse_range(range_header: str | None, ceil: int) -> tuple[int, int]:
    """Range do cliente interseccionado com [0, ceil). Default: do 0 ao fim do teto."""
    start, end = 0, ceil - 1
    if range_header and range_header.startswith("bytes="):
        spec = range_header.split("=", 1)[1].split(",")[0]
        s, _, e = spec.partition("-")
        if s.strip().isdigit():
            start = int(s)
        if e.strip().isdigit():
            end = min(int(e), ceil - 1)
    return start, end


@router.get("/media/video/{token}")
async def proxy_video(token: str, range_header: str | None = Header(default=None, alias="Range")):
    url = MEDIA_TOKENS.get(token)
    if not url:
        return Response(status_code=404)

    real_total = await _real_total(http_client, url, token)
    advertised = min(real_total, MAX_BYTES)  # teto: cliente nunca pede além disso

    start, end = _parse_range(range_header, advertised)
    if start > end or start >= advertised:
        return Response(status_code=416, headers={"Content-Range": f"bytes */{advertised}"})

    async def streamer():
        headers = {**_UPSTREAM, "Range": f"bytes={start}-{end}"}
        async with http_client.stream("GET", url, headers=headers) as resp:
            async for chunk in resp.aiter_bytes(CHUNK):
                yield chunk

    return StreamingResponse(
        streamer(),
        status_code=206,
        headers={
            "Content-Range": f"bytes {start}-{end}/{advertised}",
            "Accept-Ranges": "bytes",
            "Content-Length": str(end - start + 1),
            "Content-Type": "video/webm",
            "Cache-Control": "public, max-age=3600",
        },
    )


@router.get("/media/audio/{token}")
async def proxy_audio(token: str):
    url = AUDIO_TOKENS.get(token)
    if not url:
        return Response(status_code=404)
    try:
        # Abre o stream com o cliente global sem ler o arquivo inteiro na RAM
        async with http_client.stream("GET", url, headers=_UPSTREAM) as resp:
            if resp.status_code >= 400:
                logger.warning("audio proxy upstream %d para token %s", resp.status_code, token)
                return Response(status_code=502)
            
            content_type = resp.headers.get("content-type", "audio/mpeg")
            
            async def audio_generator():
                async for chunk in resp.aiter_bytes(CHUNK):
                    yield chunk

            return StreamingResponse(
                audio_generator(),
                media_type=content_type,
                headers={"Cache-Control": "public, max-age=3600"},
            )
    except Exception as exc:
        logger.error("audio proxy erro: %s", exc)
        return Response(status_code=502)
