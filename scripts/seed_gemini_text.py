from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed

import google.generativeai as genai

from app.config import settings
from app.db.supabase_client import get_supabase
from scripts.seed_common import build_question

LIMIT_PER_CATEGORY = 10
MAX_WORKERS = 5 

CATEGORY_MAP = {
    "movies": "movie",
    "anime": "anime",
    "games": "game",
}

TARGET_CATEGORIES = [
    "movie_plots", "anime_plots", "game_plots",
    "movie_emoji", "anime_emoji", "game_emoji",
]


def fetch_top_titles(categories: list[str], limit: int) -> list[tuple[str, str]]:
    sb = get_supabase()
    result: list[tuple[str, str]] = []
    for cat in categories:
        rows = (
            sb.table("questions")
            .select("answer, category")
            .eq("category", cat)
            .order("popularity", desc=True)
            .limit(limit)
            .execute()
            .data
        ) or []
        result.extend((r["answer"], r["category"]) for r in rows)
        print(f"  [db] {len(rows)} títulos de '{cat}'")
    return result


def call_gemini(model, prompt: str) -> str:
    return model.generate_content(prompt).text.strip()


PLOT_PROMPT = """
Você é um comediante descrevendo a obra "{title}" de forma resumida e engraçada.
Regras:
- NÃO mencione o nome da obra em nenhum momento.
- Escreva EXATAMENTE 3 frases curtas (máximo 20 palavras cada).
- Use humor, exagero, ironia ou de forma muito mal explicada.
- Cada frase em uma linha separada.
- Responda APENAS as 3 frases, sem introdução ou explicação.
""".strip()

EMOJI_PROMPT = """
Traduza o título da obra "{title}" usando APENAS emojis (máximo 6).
Regras:
- Responda APENAS com os emojis, sem texto, sem pontuação, sem explicação.
- Use emojis que representem personagens, elementos visuais ou a essência da obra.
- Seja criativo, não óbvio demais.
""".strip()


def _gen_plot(model, title: str, source_cat: str) -> dict | None:
    dest = f"{CATEGORY_MAP.get(source_cat, source_cat)}_plots"
    try:
        raw = call_gemini(model, PLOT_PROMPT.format(title=title))
        lines = [l.strip() for l in raw.split("\n") if l.strip()][:3]
        if len(lines) < 3:
            return None
        return build_question(category=dest, media_type="text", answer=title,
                              clues=lines, popularity=80, aliases=[title])
    except Exception as e:
        print(f"  [plot] Erro em '{title}': {e}")
        return None


def _gen_emoji(model, title: str, source_cat: str) -> dict | None:
    dest = f"{CATEGORY_MAP.get(source_cat, source_cat)}_emoji"
    try:
        emojis = call_gemini(model, EMOJI_PROMPT.format(title=title))
        if not emojis or len(emojis) > 30 or emojis[0].isascii():
            return None
        return build_question(category=dest, media_type="text", answer=title,
                              clues=[emojis], popularity=75, aliases=[title])
    except Exception as e:
        print(f"  [emoji] Erro em '{title}': {e}")
        return None


def main() -> None:
    if not settings.gemini_api_key:
        raise SystemExit(
            "Defina GEMINI_API_KEY no .env\n"
            "  → aistudio.google.com → Get API key (gratuito)"
        )

    genai.configure(api_key=settings.gemini_api_key)
    model = genai.GenerativeModel("gemini-3.5-flash")

    titles = fetch_top_titles(["movies", "anime", "games"], LIMIT_PER_CATEGORY)

    sb = get_supabase()
    print("\n=== Limpando categorias de destino ===")
    for cat in TARGET_CATEGORIES:
        sb.table("questions").delete().eq("category", cat).execute()
        print(f"  Deletado: {cat}")

    tasks = (
        [(model, t, c, "plot") for t, c in titles] +
        [(model, t, c, "emoji") for t, c in titles]
    )
    total = len(tasks)
    done = 0

    print(f"\n=== Gerando {total} itens em paralelo (workers={MAX_WORKERS}) ===")
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {
            executor.submit(_gen_plot if kind == "plot" else _gen_emoji, mdl, title, cat): (title, kind)
            for mdl, title, cat, kind in tasks
        }
        for fut in as_completed(futures):
            done += 1
            row = fut.result()
            if row:
                try:
                    sb.table("questions").insert(row).execute()
                    print(f"  [{done}/{total}] ✓ [{row['category']}] {row['answer']}")
                except Exception as e:
                    print(f"  [{done}/{total}] ✗ insert falhou para '{row['answer']}': {e}")
            else:
                title, kind = futures[fut]
                print(f"  [{done}/{total}] — descartado: {title} ({kind})")

    print("\n=== Concluído ===")


if __name__ == "__main__":
    main()
