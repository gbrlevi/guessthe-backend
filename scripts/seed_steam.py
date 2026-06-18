"""Reviews engraçadas da Steam → 'steam_reviews'. Sem chave. Reviews divididas em frases como pistas."""
from __future__ import annotations

import re
import time

from scripts.seed_common import build_question, http_client, replace_category

# (app_id, nome do jogo, aliases)
POPULAR_GAMES: list[tuple[int, str, list[str]]] = [
    # ==========================================
    # 1. OS PILARES DA VALVE (PC CLASSICS)
    # ==========================================
    (730,     "Counter-Strike 2",          ["cs2", "counter strike", "csgo", "cs 2", "cs"]),
    (570,     "Dota 2",                    ["dota", "dota2", "defend of the ancients"]),
    (440,     "Team Fortress 2",           ["tf2", "team fortress"]),
    (550,     "Left 4 Dead 2",             ["l4d2", "left 4 dead", "left for dead"]),
    (620,     "Portal 2",                  ["portal", "portal 2"]),
    (4000,    "Garry's Mod",               ["gmod", "garrys mod"]),
    (218620,  "Payday 2",                  ["payday 2", "payday"]),

    # ==========================================
    # 2. GRANDES RPGs & MUNDOS ABERTOS
    # ==========================================
    (271590,  "Grand Theft Auto V",        ["gta 5", "gta v", "gta", "grand theft auto"]),
    (1174180, "Red Dead Redemption 2",     ["rdr2", "red dead 2", "rdr 2", "red dead redemption"]),
    (292030,  "The Witcher 3: Wild Hunt",  ["the witcher 3", "witcher 3", "tw3"]),
    (1091500, "Cyberpunk 2077",            ["cyberpunk", "cyberpunk 2077", "cp2077"]),
    (1086940, "Baldur's Gate 3",           ["bg3", "baldurs gate", "baldurs gate 3"]),
    (489830,  "The Elder Scrolls V: Skyrim", ["skyrim", "the elder scrolls v", "tesv"]),
    (377160,  "Fallout 4",                 ["fallout 4", "fallout"]),
    (1920210, "Hogwarts Legacy",           ["hogwarts", "hogwarts legacy"]),

    # ==========================================
    # 3. SOULSLIKE & DIRETORIA DA FROM_SOFTWARE
    # ==========================================
    (1245620, "Elden Ring",                ["elden ring"]),
    (814380,  "Sekiro: Shadows Die Twice", ["sekiro", "sekiro shadows die twice"]),
    (374320,  "Dark Souls III",            ["dark souls 3", "ds3", "dark souls iii"]),
    (582010,  "Monster Hunter: World",     ["mhw", "monster hunter world", "monster hunter"]),

    # ==========================================
    # 4. SURVIVAL, CRIAÇÃO & GERENCIAMENTO
    # ==========================================
    (252490,  "Rust",                      ["rust", "rust game"]),
    (346110,  "ARK: Survival Evolved",     ["ark", "ark survival evolved"]),
    (892970,  "Valheim",                   ["valheim"]),
    (105600,  "Terraria",                  ["terraria"]),
    (264710,  "Subnautica",                ["subnautica"]),
    (108600,  "Project Zomboid",           ["project zomboid", "zomboid"]),
    (1326470, "Sons of the Forest",        ["sons of the forest", "the forest 2"]),
    (227300,  "Euro Truck Simulator 2",    ["ets2", "euro truck 2", "euro truck simulator"]),
    (427520,  "Factorio",                  ["factorio"]),
    (294100,  "RimWorld",                  ["rimworld"]),

    # ==========================================
    # 5. COMPETITIVOS & MULTIPLAYER ONLINE
    # ==========================================
    (1172470, "Apex Legends",              ["apex", "apex legends"]),
    (578080,  "PUBG: Battlegrounds",       ["pubg", "playerunknowns battlegrounds"]),
    (1938090, "Call of Duty",              ["cod", "warzone", "call of duty"]),
    (359550,  "Tom Clancy's Rainbow Six Siege", ["r6", "rainbow six siege", "rainbow six", "rss"]),
    (381210,  "Dead by Daylight",          ["dbd", "dead by daylight"]),
    (1811260, "EA SPORTS FC",              ["fifa", "fc", "ea fc"]),
    (250420,  "Warframe",                  ["warframe"]),
    (1085660, "Destiny 2",                 ["destiny 2", "destiny"]),
    (1172620, "Sea of Thieves",            ["sea of thieves", "sot"]),

    # ==========================================
    # 6. FENÔMENOS COOP, INDIES & SUCESSOS METÓRICOS
    # ==========================================
    (413150,  "Stardew Valley",            ["stardew", "stardew valley"]),
    (668580,  "Hollow Knight",             ["hollow knight"]),
    (1966720, "Lethal Company",            ["lethal company"]),
    (1623730, "Palworld",                  ["palworld"]),
    (553850,  "Helldivers 2",              ["helldivers 2", "helldivers"]),
    (1313860, "Phasmophobia",              ["phasmophobia", "phasmo"]),
    (945360,  "Among Us",                  ["among us", "amogus"]),
    (1145360, "Hades",                     ["hades"]),
    (1794680, "Vampire Survivors",         ["vampire survivors"]),
    (250900,  "The Binding of Isaac: Rebirth", ["the binding of isaac", "isaac", "binding of isaac"]),
    (242760,  "The Forest",                ["the forest"]),
    (322170,  "Geometry Dash",             ["geometry dash", "gd"]),
    (548430,  "Deep Rock Galactic",        ["drg", "deep rock"]),
    (753640,  "Outer Wilds",               ["outer wilds"]),

    # ==========================================
    # 7. SONY PORTS & OUTROS SUCESSOS
    # ==========================================
    (1716740, "God of War",                ["gow", "god of war"]),
    (1151640, "Horizon Zero Dawn",         ["horizon", "horizon zero dawn", "hzd"]),
    (2050650, "Resident Evil 4",           ["re4", "resident evil 4 remake", "resident evil 4"]),
    (289070,  "Sid Meier's Civilization VI", ["civ 6", "civilization 6", "civ vi"]),
    (646570,  "Slay the Spire",            ["slay the spire", "sts"]),
    (1364780, "Street Fighter 6",          ["sf6", "street fighter 6"]),
    (232250,  "Team Fortress Classic",     ["tfc", "team fortress classic"])
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
