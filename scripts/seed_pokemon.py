"""Pokémon via PokéAPI → 'pokemon' (imagem) + 'pokemon_cries' (áudio)."""
from __future__ import annotations

from scripts.seed_common import build_question, http_client, replace_category

API = "https://pokeapi.co/api/v2"
GEN1_COUNT = 151


def main() -> None:
    images: list[dict] = []
    cries: list[dict] = []

    with http_client() as client:
        listing = client.get(f"{API}/pokemon", params={"limit": GEN1_COUNT}).json()
        for idx, entry in enumerate(listing["results"]):
            data = client.get(entry["url"]).json()
            name: str = data["name"]
            display = name.replace("-", " ").title()
            aliases = [name, name.replace("-", " ")]

            artwork = (
                data.get("sprites", {})
                .get("other", {})
                .get("official-artwork", {})
                .get("front_default")
            )
            if artwork:
                images.append(
                    build_question(
                        category="pokemon",
                        media_type="image",
                        answer=display,
                        media_url=artwork,
                        ext_id=data["id"],
                        popularity=GEN1_COUNT - idx,
                        aliases=aliases,
                    )
                )

            cry = (data.get("cries") or {}).get("latest")
            if cry:
                cries.append(
                    build_question(
                        category="pokemon_cries",
                        media_type="audio",
                        answer=display,
                        media_url=cry,
                        ext_id=data["id"],
                        popularity=GEN1_COUNT - idx,
                        aliases=aliases,
                    )
                )
            print(f"  {data['id']:>3} {display}")

    replace_category("pokemon", images)
    replace_category("pokemon_cries", cries)


if __name__ == "__main__":
    main()
