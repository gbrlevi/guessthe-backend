"""Reviews engraçadas da Steam → 'steam_reviews'. Sem chave. Reviews divididas em frases como pistas."""
from __future__ import annotations

import re
import time

from scripts.seed_common import build_question, http_client, replace_category

# (app_id, nome do jogo, aliases)
POPULAR_GAMES: list[tuple[int, str, list[str]]] = [
    (730,     "Counter-Strike 2",         ["cs2", "counter strike", "csgo"]),
    (570,     "Dota 2",                   ["dota"]),
    (440,     "Team Fortress 2",          ["tf2"]),
    (271590,  "Grand Theft Auto V",       ["gta 5", "gta v"]),
    (1245620, "Elden Ring",               ["elden ring"]),
    (413150,  "Stardew Valley",           ["stardew"]),
    (1086940, "Baldur's Gate 3",          ["bg3", "baldurs gate"]),
    (814380,  "Sekiro",                   ["sekiro shadows die twice"]),
    (374320,  "Dark Souls III",           ["dark souls 3"]),
    (1172470, "Apex Legends",             ["apex"]),
    (578080,  "PUBG",                     ["pubg", "playerunknowns battlegrounds"]),
    (892970,  "Valheim",                  ["valheim"]),
    (1091500, "Cyberpunk 2077",           ["cyberpunk"]),
    (1716740, "God of War",               ["gow"]),
    (668580,  "Hollow Knight",            ["hollow knight"]),
    (1245620, "Elden Ring",               ["elden ring"]),
    (252490,  "Rust",                     ["rust game"]),
    (346110,  "ARK: Survival Evolved",    ["ark"]),
    (1938090, "Call of Duty",             ["cod"]),
    (1920210, "Hogwarts Legacy",          ["hogwarts"]),
]

REVIEWS_URL = "https://store.steampowered.com/appreviews/{appid}"
MAX_PER_GAME = 2
MIN_WORDS = 15


def split_clues(text: str, max_clues: int = 3) -> list[str]:
    """Divide a review em até `max_clues` frases para revelação progressiva."""
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    sentences = [s.strip() for s in sentences if len(s.split()) >= 3]
    return sentences[:max_clues] if sentences else [text[:300]]


def main() -> None:
    rows: list[dict] = []
    seen_appids: set[int] = set()

    with http_client() as client:
        for appid, game_name, aliases in POPULAR_GAMES:
            if appid in seen_appids:
                continue
            seen_appids.add(appid)

            resp = client.get(
                REVIEWS_URL.format(appid=appid),
                params={
                    "json": 1,
                    "review_type": "funny",
                    "language": "english",
                    "num_per_page": 10,
                    "filter": "recent",
                },
            ).json()

            reviews = resp.get("reviews", [])
            count = 0

            for review in reviews:
                text: str = review.get("review", "").strip()
                text = re.sub(r"\s+", " ", text)
                words = text.split()

                if len(words) < MIN_WORDS:
                    continue
                if len(words) > 80:
                    text = " ".join(words[:80]) + "…"

                clues = split_clues(text)
                if not clues:
                    continue

                rows.append(
                    build_question(
                        category="steam_reviews",
                        media_type="text",
                        answer=game_name,
                        clues=clues,
                        ext_id=f"{appid}_{review.get('recommendationid', count)}",
                        popularity=70,
                        aliases=aliases,
                    )
                )
                print(f"  {game_name} — {text[:60]}…")
                count += 1
                if count >= MAX_PER_GAME:
                    break

            time.sleep(0.5)

    replace_category("steam_reviews", rows)


if __name__ == "__main__":
    main()
