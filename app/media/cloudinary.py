from __future__ import annotations

from urllib.parse import quote

from app.config import settings

# 10 níveis progressivos: começa pixelado (8px) e chega a 512px ainda durante
# a fase de palpite. A imagem completa só aparece no reveal (full_image_url).
IMAGE_WIDTHS = [8, 12, 18, 28, 42, 64, 96, 160, 256, 512]
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


def reveal_level_for(elapsed_sec: int, duration: float, depixel_speed: int = 5) -> int:
    """Segundo decorrido → nível 0..MAX_LEVEL com velocidade controlada pelo host.

    depixel_speed 1..10:
      - 1 = muito lento: mantém pixelizado quase o round inteiro (revelação só nos últimos 20%)
      - 5 = padrão: revelação linear ao longo do round
      - 10 = rápido: despixeliza nos primeiros 40% do round
    """
    if duration <= 0:
        return MAX_LEVEL

    speed = max(1, min(10, depixel_speed))
    # Mapeia speed 1..10 para um expoente que comprime/expande a curva.
    # speed=5 → expoente=1.0 (linear); speed<5 → curva côncava (lenta no início);
    # speed>5 → curva convexa (rápida no início).
    exponent = 2.0 - (speed - 1) * (1.8 / 9)  # varia de 2.0 (speed=1) a 0.2 (speed=10)

    frac = (elapsed_sec + 1) / duration
    frac = max(0.0, min(1.0, frac))
    curved = frac ** exponent
    return max(0, min(MAX_LEVEL, int(curved * (MAX_LEVEL + 1))))
