"""Proxy de vídeo com URL opaca + suporte a Range (206).

Por que existe: a URL crua do AnimeThemes contém o nome do anime no arquivo
(KimetsuNoYaiba-OP1.webm) — mandá-la ao cliente durante a fase de palpite
vazaria a resposta. Aqui o cliente pede /media/video/{token} (token = UUID da
questão, opaco), e o servidor faz o stream do .webm sem revelar a origem.

Isso permite PRÉ-BUSCAR o vídeo durante o palpite (mesma URL no reveal → cache
hit → sem delay). Teto de bytes mantém a banda do servidor sob controle: o reveal
mostra ~6s, então poucos MB bastam.
"""
from __future__ import annotations

import logging

import httpx
from fastapi import APIRouter, Header
from fastapi.responses import Response, StreamingResponse

logger = logging.getLogger("ldkquiz.media")

router = APIRouter()

# token (UUID da questão) -> URL real do .webm. Populado pela engine no início da partida.
MEDIA_TOKENS: dict[str, str] = {}
_SIZES: dict[str, int] = {}  # cache do tamanho real (bytes) por token

# Reveal dura ~6s; ~0,5 MB/s de bitrate → poucos MB cobrem o trecho exibido.
MAX_BYTES = 8 * 1024 * 1024
CHUNK = 64 * 1024
# headers de navegador (o AnimeThemes serve 206 a qualquer um, mas mantemos consistência)
_UPSTREAM = {"User-Agent": "Mozilla/5.0", "Referer": "https://animethemes.moe/"}


def register_media(token: str, url: str) -> None:
    MEDIA_TOKENS[token] = url


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

    async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as probe:
        real_total = await _real_total(probe, url, token)
    advertised = min(real_total, MAX_BYTES)  # teto: cliente nunca pede além disso

    start, end = _parse_range(range_header, advertised)
    if start > end or start >= advertised:
        return Response(status_code=416, headers={"Content-Range": f"bytes */{advertised}"})

    async def streamer():
        headers = {**_UPSTREAM, "Range": f"bytes={start}-{end}"}
        async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
            async with client.stream("GET", url, headers=headers) as resp:
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
