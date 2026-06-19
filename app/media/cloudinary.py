from __future__ import annotations

from urllib.parse import quote

from app.config import settings

IMAGE_WIDTHS = [8, 16, 32, 64]  # nível 0..3: imagem vai ficando mais nítida
MAX_LEVEL = len(IMAGE_WIDTHS) - 1


def _base() -> str:
    return f"https://res.cloudinary.com/{settings.cloudinary_cloud_name}"


def _enc(url: str) -> str:
    return quote(url, safe="")


def pixel_image_url(original_url: str, level: int) -> str:
    """Miniatura pixelada para o nível atual (durante o round)."""
    w = IMAGE_WIDTHS[max(0, min(level, MAX_LEVEL))]
    return f"{_base()}/image/fetch/w_{w},c_fill,f_auto/{_enc(original_url)}"


def full_image_url(original_url: str) -> str:
    """Imagem sem pixelizar — só no REVEAL."""
    return f"{_base()}/image/fetch/f_auto/{_enc(original_url)}"


def full_audio_url(original_url: str) -> str:
    """Áudio original via fetch (categorias AUDIO: cries, sfx, etc.)."""
    return f"{_base()}/video/fetch/{_enc(original_url)}"


def question_audio_url(original_url: str, seconds: int) -> str:
    """Áudio (mp3) do .webm para a fase de pergunta, limitado à duração do round.
    Formato e clipe FIXOS → mesma chave de cache p/ aquecimento server-side e reuso no cliente."""
    seconds = max(1, seconds)
    return f"{_base()}/video/fetch/f_mp3,eo_{seconds}/{_enc(original_url)}"


def reveal_level_for(elapsed_sec: int, duration: float) -> int:
    """Segundo decorrido → nível 0..MAX_LEVEL (divide o round em faixas iguais)."""
    if duration <= 0:
        return MAX_LEVEL
    frac = (elapsed_sec + 1) / duration
    return max(0, min(MAX_LEVEL, int(frac * (MAX_LEVEL + 1))))
