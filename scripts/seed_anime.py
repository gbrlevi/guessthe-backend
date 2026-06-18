from __future__ import annotations

import time

from scripts.seed_common import build_question, http_client, replace_category

API = "https://graphql.anilist.co"
PAGES = 4      # 50 por página → 200 anime top
SLEEP = 1.5

QUERY = """
query ($page: Int) {
  Page(page: $page, perPage: 50) {
    pageInfo { hasNextPage }
    media(type: ANIME, format: TV, sort: POPULARITY_DESC) {
      id
      idMal
      title { romaji english }
      popularity
      coverImage { large }
    }
  }
}
"""


def main() -> None:
    rows: list[dict] = []
    seen: set[int] = set()  # AniList IDs para dedup intra-run

    with http_client() as client:
        for page in range(1, PAGES + 1):
            r = client.post(
                API,
                json={"query": QUERY, "variables": {"page": page}},
                headers={"Content-Type": "application/json", "Accept": "application/json"},
                timeout=30.0,
            )
            if r.status_code != 200 or not r.content:
                print(f"  AniList página {page}: status {r.status_code} — aguardando 10s")
                time.sleep(10)
                continue

            page_data = r.json().get("data", {}).get("Page", {})
            media_list = page_data.get("media", [])
            if not media_list:
                print(f"  AniList: sem resultados na página {page}")
                break

            for item in media_list:
                anilist_id: int = item.get("id", 0)
                if anilist_id in seen:
                    continue
                seen.add(anilist_id)

                title_en = (item.get("title") or {}).get("english") or ""
                title_jp = (item.get("title") or {}).get("romaji") or ""
                image_url = (item.get("coverImage") or {}).get("large")

                if not image_url or not (title_en or title_jp):
                    continue

                answer = title_en or title_jp
                aliases = list({title_en, title_jp} - {""})

                rows.append(
                    build_question(
                        category="anime",
                        media_type="image",
                        answer=answer,
                        media_url=image_url,
                        ext_id=anilist_id,
                        popularity=(item.get("popularity") or 0) // 1000,
                        aliases=aliases,
                    )
                )
                print(f"  {answer}")

            if not page_data.get("pageInfo", {}).get("hasNextPage"):
                break

            time.sleep(SLEEP)

    replace_category("anime", rows)


if __name__ == "__main__":
    main()
