from __future__ import annotations

import time

from scripts.seed_common import (
    audio_link_from,
    build_question,
    http_client,
    pick_smallest_webm,
    replace_category,
)

AT_API = "https://api.animethemes.moe"
ANILIST_API = "https://graphql.anilist.co"

AT_PAGES = 80
AT_SLEEP = 0.3

ANILIST_PAGES = 4   
ANILIST_SLEEP = 1.5

ANILIST_QUERY = """
query ($page: Int) {
  Page(page: $page, perPage: 50) {
    pageInfo { hasNextPage }
    media(type: ANIME, format: TV, sort: POPULARITY_DESC) {
      id
      idMal
      title { romaji english }
      popularity
    }
  }
}
"""


# ── helpers ──────────────────────────────────────────────────────────────────

def _mal_id_from(anime: dict) -> int | None:
    for resource in anime.get("resources") or []:
        if resource.get("site") == "MyAnimeList":
            try:
                return int(resource["external_id"])
            except (KeyError, TypeError, ValueError):
                pass
    return None


def _best_video(anime: dict) -> tuple[str | None, str | None, str]:
    """(menor .webm, link .ogg do áudio, tipo do tema). Menor variante → cabe no
    transcode do Cloudinary e baixa rápido; .ogg → áudio leve p/ a pergunta."""
    themes = anime.get("animethemes") or []
    ops = [t for t in themes if t.get("type") == "OP"]
    eds = [t for t in themes if t.get("type") == "ED"]
    candidates = ops if ops else eds
    if not candidates:
        return None, None, "OP"

    theme = candidates[0]
    theme_type = theme.get("type", "OP")
    videos: list[dict] = []
    for entry in theme.get("animethemeentries") or []:
        videos.extend(entry.get("videos") or [])

    best = pick_smallest_webm(videos)
    if not best:
        return None, None, theme_type
    return best.get("link"), audio_link_from(videos), theme_type


# ── etapa 1: catálogo AnimeThemes ────────────────────────────────────────────

def build_at_map(client) -> dict[int, dict]:
    """Retorna {mal_id: {name, video_url, theme_type, theme_id}} para o catálogo inteiro."""
    result: dict[int, dict] = {}

    for page in range(1, AT_PAGES + 1):
        r = client.get(
            f"{AT_API}/anime",
            params={
                "page[size]": 50,
                "page[number]": page,
                "include": "animethemes.animethemeentries.videos.audio,resources",
            },
            timeout=60.0,
        )
        if r.status_code != 200 or not r.content:
            print(f"  AnimeThemes página {page}: status {r.status_code} — aguardando 5s")
            time.sleep(5)
            continue

        resp = r.json()
        batch = resp.get("anime", [])
        if not batch:
            print(f"  AnimeThemes: catálogo esgotado na página {page}")
            break

        for anime in batch:
            mal_id = _mal_id_from(anime)
            if not mal_id:
                continue

            video_url, audio_url, theme_type = _best_video(anime)
            if not video_url:
                continue

            themes = anime.get("animethemes") or []
            candidates = [t for t in themes if t.get("type") == theme_type]
            theme_id = candidates[0].get("id") if candidates else None

            # mantém o primeiro encontrado; catálogo não tem ordem de popularidade
            if mal_id not in result:
                result[mal_id] = {
                    "name": anime.get("name", ""),
                    "video_url": video_url,
                    "audio_url": audio_url,
                    "theme_type": theme_type,
                    "theme_id": theme_id,
                }

        time.sleep(AT_SLEEP)

    print(f"  AnimeThemes: {len(result)} anime com MAL ID + vídeo mapeados")
    return result


# ── etapa 2: ranking AniList ──────────────────────────────────────────────────

def fetch_anilist_ranking(client) -> list[dict]:
    """Retorna top anime do AniList ordenados por popularity (mais popular primeiro)."""
    ranking: list[dict] = []
    seen_ids: set[int] = set()

    for page in range(1, ANILIST_PAGES + 1):
        r = client.post(
            ANILIST_API,
            json={"query": ANILIST_QUERY, "variables": {"page": page}},
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            timeout=30.0,
        )
        if r.status_code != 200 or not r.content:
            print(f"  AniList página {page}: status {r.status_code} — aguardando 10s")
            time.sleep(10)
            continue

        page_data = r.json().get("data", {}).get("Page", {})
        media_list = page_data.get("media", [])

        for item in media_list:
            anilist_id: int = item.get("id", 0)
            mal_id: int | None = item.get("idMal")
            popularity: int = item.get("popularity") or 0

            if not mal_id or anilist_id in seen_ids:
                continue
            seen_ids.add(anilist_id)

            ranking.append({
                "mal_id": mal_id,
                "popularity": popularity,
                "title_en": (item.get("title") or {}).get("english") or "",
                "title_jp": (item.get("title") or {}).get("romaji") or "",
            })

        if not page_data.get("pageInfo", {}).get("hasNextPage"):
            break

        time.sleep(ANILIST_SLEEP)

    ranking.sort(key=lambda x: x["popularity"], reverse=True)
    return ranking


# ── etapa 3: cruzamento e geração ────────────────────────────────────────────

def main() -> None:
    rows: list[dict] = []

    with http_client() as client:
        print("=== Etapa 1: AnimeThemes (catálogo + MAL IDs) ===")
        at_map = build_at_map(client)

        print("=== Etapa 2: AniList top anime por popularity ===")
        anilist_ranking = fetch_anilist_ranking(client)

    print("=== Etapa 3: cruzamento ===")
    print(f"  AniList: {len(anilist_ranking)} anime | AnimeThemes com vídeo: {len(at_map)}")

    seen_mal: set[int] = set()
    missed = 0

    for item in anilist_ranking:
        mal_id = item["mal_id"]
        if mal_id in seen_mal:
            continue
        seen_mal.add(mal_id)

        if mal_id not in at_map:
            missed += 1
            continue

        at = at_map[mal_id]
        title_en = item["title_en"]
        title_jp = item["title_jp"]
        answer = title_en or title_jp or at["name"]
        aliases = list({title_en, title_jp, at["name"]} - {""})
        theme_type = at["theme_type"]
        type_label = "Abertura" if theme_type == "OP" else "Encerramento"

        rows.append(
            build_question(
                category="anime_openings",
                media_type="video",
                answer=answer,
                media_url=at["video_url"],
                audio_url=at.get("audio_url"),
                ext_id=f"{mal_id}_{at['theme_id']}",
                popularity=item["popularity"] // 1000,
                aliases=aliases,
                clues=[f"{type_label} de um anime popular"],
            )
        )

        name_safe = answer.encode("ascii", errors="replace").decode()
        print(f"  {name_safe:<42} {item['popularity']:>7} pop")

    print(f"\n{len(rows)} questões geradas | {missed} sem vídeo no AnimeThemes.")
    replace_category("anime_openings", rows)


if __name__ == "__main__":
    main()
