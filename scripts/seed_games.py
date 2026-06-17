"""Jogos via RAWG → 'games' (capa). Requer RAWG_API_KEY."""
from __future__ import annotations

from app.config import settings
from scripts.seed_common import build_question, http_client, replace_category

API = "https://api.rawg.io/api"
PAGES = 4


def main() -> None:
    if not settings.rawg_api_key:
        raise SystemExit("Defina RAWG_API_KEY no .env (rawg.io → Developer → API key).")

    rows: list[dict] = []

    with http_client() as client:
        for page in range(1, PAGES + 1):
            resp = client.get(
                f"{API}/games",
                params={
                    "key": settings.rawg_api_key,
                    "ordering": "-added",
                    "page_size": 40,
                    "page": page,
                    "exclude_additions": True,
                },
            ).json()

            if "results" not in resp:
                raise SystemExit(f"RAWG retornou erro: {resp.get('detail', resp)}")

            for game in resp["results"]:
                name = game.get("name")
                image = game.get("background_image")
                if not name or not image:
                    continue

                rows.append(
                    build_question(
                        category="games",
                        media_type="image",
                        answer=name,
                        media_url=image,
                        ext_id=game["id"],
                        popularity=game.get("added", 0) // 1000,
                        aliases=[name],
                    )
                )
                print(f"  {name}")

    replace_category("games", rows)


if __name__ == "__main__":
    main()
