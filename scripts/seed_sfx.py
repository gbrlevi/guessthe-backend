"""SFX via Freesound → 'sfx'. Requer FREESOUND_API_KEY. Previews HQ-MP3 são CDN público."""
from __future__ import annotations

import time

from app.config import settings
from scripts.seed_common import build_question, http_client, replace_category

API = "https://freesound.org/apiv2"

QUERIES: list[tuple[str, str, list[str]]] = [
    # ==========================================
    # 1. RETRO, ARCADE & PLATAFORMAS CLÁSSICAS
    # ==========================================
    ("mario coin collect",             "Super Mario",           ["mario", "super mario", "smw", "smb"]),
    ("mario jump sound",               "Super Mario",           ["mario", "super mario"]),
    ("pacman eating",                  "Pac-Man",               ["pacman", "pac man"]),
    ("pacman death",                   "Pac-Man",               ["pacman", "pac man"]),
    ("sonic ring collect",             "Sonic",                 ["sonic the hedgehog", "sonic"]),
    ("tetris line clear",              "Tetris",                ["tetris"]),
    ("crash bandicoot box break",      "Crash Bandicoot",       ["crash"]),
    ("metal slug heavy machine gun",   "Metal Slug",            ["metal slug"]),
    ("donkey kong death",              "Donkey Kong",           ["donkey kong", "dk"]),
    ("zelda chest open item get",      "The Legend of Zelda",   ["zelda", "tloz"]),
    ("zelda secret chime",             "The Legend of Zelda",   ["zelda", "tloz"]),

    # ==========================================
    # 2. LUTAS, TIRO & FPS LENDÁRIOS
    # ==========================================
    ("street fighter hadouken",        "Street Fighter",        ["street fighter", "sf"]),
    ("mortal kombat finish him",       "Mortal Kombat",         ["mortal kombat", "mk"]),
    ("mortal kombat toasty",           "Mortal Kombat",         ["mortal kombat", "mk"]),
    ("counter strike headshot",        "Counter-Strike",        ["cs", "counter strike", "csgo", "cs2"]),
    ("counter strike bomb planted",    "Counter-Strike",        ["cs", "counter strike", "csgo", "cs2"]),
    ("half life crowbar",              "Half-Life",             ["half life", "hl"]),
    ("half life hev battery",          "Half-Life",             ["half life", "hl", "hev"]),
    ("doom 1993 shotgun reload",       "DOOM",                  ["doom"]),
    ("doom 1993 door open",            "DOOM",                  ["doom"]),
    ("halo multiplayer announcer",     "Halo",                  ["halo"]),
    ("unreal tournament monster kill", "Unreal Tournament",     ["unreal tournament", "ut"]),

    # ==========================================
    # 3. COMPETITIVOS & MULTIPLAYERS MODERNOS
    # ==========================================
    ("valorant headshot ding",         "Valorant",              ["val", "vava", "valorant"]),
    ("cod hitmarker",                  "Call of Duty",          ["cod", "call of duty", "warzone"]),
    ("league of legends missing ping", "League of Legends",     ["lol", "league of legends", "league"]),
    ("overwatch headshot",             "Overwatch",             ["ow", "overwatch", "overwatch 2"]),
    ("apex legends shield crack",      "Apex Legends",          ["apex"]),
    ("fortnite chest open",            "Fortnite",              ["fortnite"]),
    ("pubg frying pan hit",            "PUBG",                  ["pubg", "playerunknowns battlegrounds"]),
    ("rocket league goal siren",       "Rocket League",         ["rocket league", "rl"]),
    ("helldivers 2 stratagem beep",    "Helldivers 2",          ["helldivers", "helldivers 2"]),

    # ==========================================
    # 4. RPG, ESTRATÉGIA & IMERSÃO (PC/CONSOLE)
    # ==========================================
    ("metal gear alert exclamation",   "Metal Gear Solid",      ["mgs", "metal gear"]),
    ("pokemon center healing machine", "Pokémon",               ["pokemon", "pokémon"]),
    ("gta san andreas mission passed", "GTA San Andreas",       ["gta", "grand theft auto", "gta sa"]),
    ("gta v wasted death",             "GTA V",                 ["gta", "grand theft auto", "gta v", "gta 5"]),
    ("skyrim level up",                "Skyrim",                ["the elder scrolls", "tesv", "skyrim"]),
    ("dark souls death you died",      "Dark Souls",            ["dark souls", "elden ring", "demons souls"]),
    ("dark souls parry sound",         "Dark Souls",            ["dark souls", "elden ring"]),
    ("fallout vats beep",              "Fallout",               ["fallout"]),
    ("world of warcraft murloc",       "World of Warcraft",     ["wow", "world of warcraft"]),
    ("world of warcraft level up",     "World of Warcraft",     ["wow", "world of warcraft"]),
    ("age of empires wololo",          "Age of Empires",        ["aoe", "age of empires"]),
    ("starcraft stimpack",             "StarCraft",             ["starcraft", "sc"]),

    # ==========================================
    # 5. INDIES, PHENOMENOS MOBILE & COOP
    # ==========================================
    ("minecraft damage",               "Minecraft",             ["minecraft"]),
    ("among us kill",                  "Among Us",              ["among us", "amogus"]),
    ("among us emergency meeting",     "Among Us",              ["among us", "amogus"]),
    ("roblox death",                   "Roblox",                ["roblox"]),
    ("clash royale hog rider",         "Clash Royale",          ["clash", "clash royale"]),
    ("angry birds pig laugh",          "Angry Birds",           ["angry birds"]),
    ("undertale sans speak",           "Undertale",             ["undertale"]),
    ("the sims buying sound",          "The Sims",              ["sims", "the sims"]),
    ("plants vs zombies brains",       "Plants vs. Zombies",    ["pvz", "plants vs zombies"]),
    ("celeste dash sound",             "Celeste",               ["celeste"]),
    ("lethal company landmine",        "Lethal Company",        ["lethal company"]),

    # ==========================================
    # 6. TERROR, SUSPENSE & CASUAIS
    # ==========================================
    ("fnaf jumpscare scream",          "Five Nights at Freddy's", ["fnaf", "five nights at freddys"]),
    ("resident evil title voice",      "Resident Evil",         ["re", "resident evil", "biohazard"]),
    ("silent hill radio static",       "Silent Hill",           ["silent hill"]),
    ("left 4 dead witch cry",          "Left 4 Dead",           ["l4d", "l4d2", "left 4 dead"]),
    ("dead by daylight skill check",   "Dead by Daylight",      ["dbd", "dead by daylight"]),
    ("wii sports strike cheer",        "Wii Sports",            ["wii", "wii sports"]),
    ("guitar hero star power",         "Guitar Hero",           ["guitar hero", "gh"]),
    ("phoenix wright objection",       "Phoenix Wright",        ["phoenix wright", "ace attorney"])
]

MAX_PER_QUERY = 2


def main() -> None:
    if not settings.freesound_api_key:
        raise SystemExit(
            "Defina FREESOUND_API_KEY no .env\n"
            "  → freesound.org → API → Apply for credentials (gratuito)"
        )

    rows: list[dict] = []

    with http_client() as client:
        for query, answer, aliases in QUERIES:
            resp = client.get(
                f"{API}/search/text/",
                params={
                "query": query,
                "token": settings.freesound_api_key,
                "fields": "id,name,previews,duration",
                "page_size": MAX_PER_QUERY,
                "filter": "duration:[0.1 TO 5.0]", 
            },
            ).json()

            results = resp.get("results", [])
            if not results and "detail" in resp:
                print(f"  Freesound erro em '{query}': {resp['detail']}")
                continue

            for sound in results[:MAX_PER_QUERY]:
                preview_url = sound.get("previews", {}).get("preview-hq-mp3")
                if not preview_url:
                    continue

                rows.append(
                    build_question(
                        category="sfx",
                        media_type="audio",
                        answer=answer,
                        media_url=preview_url,
                        ext_id=sound["id"],
                        popularity=60,
                        aliases=aliases,
                    )
                )
                print(f"  {answer} — {sound['name']}")

            time.sleep(0.3)

    replace_category("sfx", rows)


if __name__ == "__main__":
    main()
