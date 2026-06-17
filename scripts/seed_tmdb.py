from __future__ import annotations

from app.config import settings
from scripts.seed_common import build_question, http_client, replace_category

API = "https://api.themoviedb.org/3"
IMG_BASE = "https://image.tmdb.org/t/p/w780"
PAGES = 5  # ~20 filmes/página


def main() -> None:
    if not settings.tmdb_api_key:
        raise SystemExit("Defina TMDB_API_KEY no .env antes de rodar este seeder.")

    rows: list[dict] = []
    with http_client() as client:
        for page in range(1, PAGES + 1):
            resp = client.get(
                f"{API}/movie/popular",
                params={"api_key": settings.tmdb_api_key, "language": "pt-BR", "page": page},
            ).json()
            if "results" not in resp:
                raise SystemExit(f"TMDb retornou erro: {resp.get('status_message', resp)}")
            for movie in resp["results"]:
                poster = movie.get("poster_path")
                if not poster:
                    continue
                title = movie.get("title") or movie.get("original_title")
                aliases = [title, movie.get("original_title", "")]
                rows.append(
                    build_question(
                        category="movies",
                        media_type="image",
                        answer=title,
                        media_url=f"{IMG_BASE}{poster}",
                        ext_id=movie["id"],
                        popularity=round(movie.get("popularity", 0)),
                        aliases=aliases,
                    )
                )
                print(f"  {title}")

    replace_category("movies", rows)


if __name__ == "__main__":
    main()
