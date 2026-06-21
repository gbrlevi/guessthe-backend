from __future__ import annotations

import difflib
import re
import unicodedata

MAX_POINTS = 1000

_CLOSE_THRESHOLD = 0.55
_CLOSE_MIN_LEN = 3


def compute_score(elapsed: float, duration: float) -> int:
    """cai linearmente de 1000 até ~500 conforme o tempo passa."""
    if duration <= 0:
        return MAX_POINTS
    ratio = max(0.0, 1.0 - (elapsed / duration))
    return round(MAX_POINTS * (0.5 + 0.5 * ratio))


def normalize(text: str) -> str:
    """minúsculas, sem acentos, sem pontuação. Ex.: "Pokémon: Pikachu!" → "pokemon pikachu" """
    if not text:
        return ""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def is_close_answer(guess: str, accepted_answers: list[str]) -> bool:
    """Retorna True se o palpite normalizado é similar (mas não igual) a alguma resposta aceita.
    accepted_answers já devem estar normalizados (como armazenados no banco)."""
    normalized = normalize(guess)
    if len(normalized) < _CLOSE_MIN_LEN:
        return False
    for answer in accepted_answers:
        ratio = difflib.SequenceMatcher(None, normalized, answer).ratio()
        if ratio >= _CLOSE_THRESHOLD:
            return True
    return False
