from __future__ import annotations

import re
import unicodedata

MAX_POINTS = 1000


def compute_score(elapsed: float, duration: float) -> int:
    """Kahoot-style: cai linearmente de 1000 até ~500 conforme o tempo passa."""
    if duration <= 0:
        return MAX_POINTS
    ratio = max(0.0, 1.0 - (elapsed / duration))
    return round(MAX_POINTS * (0.5 + 0.5 * ratio))


def normalize(text: str) -> str:
    """Minúsculas, sem acentos, sem pontuação. Ex.: "Pokémon: Pikachu!" → "pokemon pikachu" """
    if not text:
        return ""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text
