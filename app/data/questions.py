from __future__ import annotations

import math
import random
from concurrent.futures import ThreadPoolExecutor, as_completed

from app.db.supabase_client import get_supabase
from app.game.termo import fold_upper
from app.models.schemas import CategoryInfo, MediaType, Question

POOL_PER_CAT = 60  # máx de questões buscadas por categoria


def _to_question(row: dict) -> Question:
    return Question(
        id=str(row["id"]),
        category=row["category"],
        media_type=row["media_type"],
        answer=row["answer"],
        accepted_answers=row.get("accepted_answers") or [],
        media_url=row.get("media_url"),
        clues=row.get("clues") or [],
        metadata=row.get("metadata") or {},
        popularity=row.get("popularity") or 0,
    )


def list_categories() -> list[CategoryInfo]:
    sb = get_supabase()
    rows = sb.rpc("category_counts", {}).execute().data or []
    return [CategoryInfo(category=r["category"], count=r["count"]) for r in rows]


def fetch_pool(categories: list[str]) -> list[Question]:
    """Busca um pool balanceado: mesma cota por categoria para evitar que
    uma categoria popular domine o deck quando múltiplas estão selecionadas."""
    sb = get_supabase()

    if not categories:
        # sem filtro: busca global com limit maior para variedade usando RPC aleatório
        res = (
            sb.rpc("get_random_questions", {"p_category": None, "p_limit": 300})
            .execute()
        )
        return [_to_question(r) for r in (res.data or [])]

    # Com categorias: busca em paralelo (uma thread por categoria) para evitar
    # N round-trips sequenciais que travavam o event loop.
    def _fetch_cat(cat: str) -> list[Question]:
        res = (
            sb.rpc("get_random_questions", {"p_category": cat, "p_limit": POOL_PER_CAT})
            .execute()
        )
        qs = [_to_question(r) for r in (res.data or [])]
        random.shuffle(qs)
        return qs

    all_questions: list[Question] = []
    max_workers = min(len(categories), 8)
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_fetch_cat, cat): cat for cat in categories}
        for fut in as_completed(futures):
            all_questions.extend(fut.result())

    return all_questions


def build_deck(categories: list[str], total_rounds: int) -> list[Question]:
    """Monta o deck garantindo distribuição proporcional entre categorias.

    Quando há N categorias e K rounds pedidos, cada categoria contribui com
    ≈ K/N questões. Se uma categoria tiver poucas questões, as demais preenchem
    o espaço restante para atingir total_rounds."""
    pool = fetch_pool(categories)
    if not pool:
        return []

    if not categories or len(categories) <= 1:
        # sem filtro ou categoria única: embaralha e fatia normalmente
        random.shuffle(pool)
        if len(pool) >= total_rounds:
            return pool[:total_rounds]
        deck = list(pool)
        while len(deck) < total_rounds:
            deck.append(random.choice(pool))
        return deck

    # Agrupa por categoria e define cota por categoria
    by_cat: dict[str, list[Question]] = {}
    for q in pool:
        by_cat.setdefault(q.category, []).append(q)

    # Cota base = ceil(total_rounds / nº de categorias com questões)
    cats_with_qs = [c for c in categories if by_cat.get(c)]
    if not cats_with_qs:
        return []

    quota = math.ceil(total_rounds / len(cats_with_qs))

    deck: list[Question] = []
    leftover: list[Question] = []

    for cat in cats_with_qs:
        qs = by_cat[cat]
        random.shuffle(qs)
        deck.extend(qs[:quota])
        leftover.extend(qs[quota:])

    # Se o deck ultrapassou, corta; se ficou curto, preenche com leftover
    if len(deck) >= total_rounds:
        random.shuffle(deck)
        return deck[:total_rounds]

    random.shuffle(leftover)
    deck.extend(leftover[: total_rounds - len(deck)])
    random.shuffle(deck)
    return deck[:total_rounds]


def build_termo_deck(categories: list[str], total_rounds: int) -> list[Question]:
    """Deck do modo Termo. Considera só categorias `termo_*` e mantém apenas
    questões de texto cuja resposta (maiúscula, sem acento) seja alfabética e
    de 3 a 11 letras — reaproveita o balanceamento de `build_deck`."""
    cats = [c for c in categories if c.startswith("termo_")]
    deck = build_deck(cats, total_rounds)
    out: list[Question] = []
    for q in deck:
        w = fold_upper(q.answer)
        if q.media_type == MediaType.TEXT and w.isalpha() and 3 <= len(w) <= 11:
            out.append(q)
    return out


def build_mixed_deck(categories: list[str], total_rounds: int, termo_ratio: float) -> list[Question]:
    """Deck do modo MISTO: intercala questões de quiz e palavras de Termo na mesma
    partida. `termo_ratio` (0..1) é a fração de rodadas de Termo. Se só houver um
    tipo de categoria selecionado, cai no deck puro daquele tipo."""
    termo_cats = [c for c in categories if c.startswith("termo_")]
    quiz_cats = [c for c in categories if not c.startswith("termo_")]
    if not termo_cats:
        return build_deck(quiz_cats, total_rounds)
    if not quiz_cats:
        return build_termo_deck(termo_cats, total_rounds)

    ratio = max(0.0, min(1.0, termo_ratio))
    # garante ao menos 1 rodada de cada lado quando ambos os tipos foram escolhidos
    n_termo = max(1, min(total_rounds - 1, round(total_rounds * ratio)))
    n_quiz = total_rounds - n_termo

    deck = build_termo_deck(termo_cats, n_termo)[:n_termo] + build_deck(quiz_cats, n_quiz)[:n_quiz]
    random.shuffle(deck)
    return deck


def random_question(categories: list[str] | None = None) -> Question | None:
    pool = fetch_pool(categories or [])
    return random.choice(pool) if pool else None


def all_answers(category: str) -> list[str]:
    """Todas as respostas distintas de uma categoria, para autocomplete local
    no cliente (sem 1 requisição por tecla). Pagina porque o Supabase devolve
    no máx. 1000 linhas por consulta."""
    sb = get_supabase()
    seen: set[str] = set()
    result: list[str] = []
    page_size = 1000
    page = 0
    while True:
        rows = (
            sb.table("questions")
            .select("answer")
            .eq("category", category)
            .range(page * page_size, page * page_size + page_size - 1)
            .execute()
            .data
        ) or []
        for r in rows:
            a = r["answer"]
            if a not in seen:
                seen.add(a)
                result.append(a)
        if len(rows) < page_size:
            break
        page += 1
    return result


def autocomplete_answers(category: str, q: str, limit: int = 8) -> list[str]:
    if len(q) < 3:
        return []
    sb = get_supabase()
    rows = (
        sb.table("questions")
        .select("answer")
        .eq("category", category)
        .ilike("answer", f"%{q}%")
        .limit(limit)
        .execute()
        .data
    ) or []
    seen: set[str] = set()
    result: list[str] = []
    for r in rows:
        a = r["answer"]
        if a not in seen:
            seen.add(a)
            result.append(a)
    return result
