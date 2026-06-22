"""Lógica pura do modo Termo: coloração de letras, validação, pontuação e
builders das mensagens WS.

Fronteira anti-cheat: NENHUM builder serializa `word`/`hint` antes do REVEAL.
A palavra secreta só aparece em `msg_termo_reveal`; a dica, em `msg_termo_hint`
(disparada pelo motor só após `termo_hint_delay`)."""
from __future__ import annotations

import unicodedata
from typing import TYPE_CHECKING

from app.game.scoring import compute_score

if TYPE_CHECKING:
    from app.game.state import Player, Room, TermoRoundState, TermoSubmission

# Pontuação do Tabuleiro Compartilhado (arena)
CORRECT_POINTS = 10       # por nova letra "correct" descoberta globalmente
PRESENT_POINTS = 5        # por nova letra "present" descoberta globalmente
FULL_SOLVE_POINTS = 100   # acerto total encerra a rodada

# Pontuação do PVP Individual (confirmado com o usuário):
#   compute_score(tempo) + 50*tentativas_restantes + 300 ao primeiro a resolver
PVP_FIRST_SOLVER_BONUS = 300
PVP_ATTEMPT_BONUS = 50


def fold_upper(s: str) -> str:
    """MAIÚSCULA sem acentos. Ex.: "pokémon" → "POKEMON" (mesma decomposição
    NFKD usada por scoring.normalize, mantendo o casamento consistente)."""
    if not s:
        return ""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return s.upper()


def validate_guess_shape(guess: str, length: int) -> str | None:
    """Valida formato (tamanho + apenas letras). Retorna o palpite normalizado
    (MAIÚSCULA sem acento) ou None se inválido. Sem checagem de dicionário."""
    g = fold_upper((guess or "").strip())
    if len(g) != length or not g.isalpha():
        return None
    return g


def color_guess(guess: str, word: str) -> list[str]:
    """Coloração estilo Wordle/Termo. `guess` e `word` MAIÚSCULOS e de mesmo
    tamanho (garantido pelo chamador via validate_guess_shape).

    Algoritmo de duas passadas para tratar letras repetidas corretamente:
    1ª passada marca os verdes e consome a contagem da letra; 2ª passada só
    marca amarelo se ainda restar cópia daquela letra. Ex.: segredo "MARIO",
    palpite "MAMMA" → ["correct","correct","absent","absent","absent"]."""
    n = len(word)
    colors = ["absent"] * n
    counts: dict[str, int] = {}
    for ch in word:
        counts[ch] = counts.get(ch, 0) + 1
    for i in range(n):                       # 1ª passada: verdes
        if guess[i] == word[i]:
            colors[i] = "correct"
            counts[guess[i]] -= 1
    for i in range(n):                       # 2ª passada: amarelos se sobrar cópia
        if colors[i] == "correct":
            continue
        ch = guess[i]
        if counts.get(ch, 0) > 0:
            colors[i] = "present"
            counts[ch] -= 1
    return colors


def is_solved(colors: list[str]) -> bool:
    return bool(colors) and all(c == "correct" for c in colors)


def score_shared_guess(tr: "TermoRoundState", colors: list[str], guess: str) -> int:
    """Pontos parciais na arena. Conjuntos de descoberta GLOBAIS: só o PRIMEIRO
    a revelar cada verde (por posição) / amarelo (por letra) pontua.

    Verdes contam por posição; amarelos contam por letra. Mutaciona `tr`."""
    gained = 0
    for i, c in enumerate(colors):
        if c == "correct" and i not in tr.discovered_correct:
            tr.discovered_correct.add(i)
            gained += CORRECT_POINTS
    for i, c in enumerate(colors):
        if c == "present" and guess[i] not in tr.discovered_present:
            tr.discovered_present.add(guess[i])
            gained += PRESENT_POINTS
    return gained


def score_pvp_solve(elapsed: float, duration: float, attempts_left: int, is_first: bool) -> int:
    return (
        compute_score(elapsed, duration)
        + max(0, attempts_left) * PVP_ATTEMPT_BONUS
        + (PVP_FIRST_SOLVER_BONUS if is_first else 0)
    )


# ----- Builders das mensagens WS (fronteira anti-cheat) -----

def msg_termo_question_start(room: "Room") -> dict:
    """Início da rodada de Termo. NÃO contém a palavra nem a dica — só o tamanho,
    o tema e os parâmetros para o cliente montar a grade."""
    tr = room.termo_round
    assert tr is not None
    return {
        "type": "question_start",
        "round": room.current_round,
        "total_rounds": room.total_rounds,
        # Sempre "termo": é o modo DA RODADA. No modo MISTO, room.game_mode é "misto",
        # mas o cliente precisa renderizar a grade de Termo nesta rodada.
        "game_mode": "termo",
        "termo_mode": room.termo_mode.value,
        "theme": tr.theme,
        "length": tr.length,
        "max_attempts": tr.max_attempts,
        "submission_cooldown": room.submission_cooldown,
        "hint_delay": room.termo_hint_delay,
        "duration": room.termo_round_duration,
    }


def msg_termo_hint(tr: "TermoRoundState") -> dict:
    return {"type": "termo_hint", "hint": tr.hint}


def msg_cooldown_error(retry_after: float) -> dict:
    return {
        "type": "cooldown_error",
        "message": "Aguarde o tempo de cooldown.",
        "retry_after": round(retry_after, 2),
    }


def msg_guess_error(reason: str, expected_length: int | None = None) -> dict:
    msg: dict = {"type": "guess_error", "reason": reason}
    if expected_length is not None:
        msg["expected_length"] = expected_length
    return msg


def msg_guess_result(letters: list[str], colors: list[str], attempt_index: int,
                     attempts_left: int | None, solved: bool) -> dict:
    """Resultado completo enviado SÓ ao autor do palpite (ele já digitou as letras)."""
    return {
        "type": "guess_result",
        "accepted": True,
        "letters": letters,
        "colors": colors,
        "attempt_index": attempt_index,
        "attempts_left": attempts_left,
        "solved": solved,
    }


def msg_opponent_progress(player: "Player", colors: list[str], attempts_left: int, solved: bool) -> dict:
    """Progresso CENSURADO de um oponente — apenas as cores, nunca as letras."""
    return {
        "type": "opponent_progress",
        "player_id": player.id,
        "player_name": player.name,
        "avatar": player.avatar,
        "colors": colors,
        "attempts_left": attempts_left,
        "solved": solved,
    }


def msg_shared_grid_update(sub: "TermoSubmission", delta_score: int) -> dict:
    """Palpite ABERTO no tabuleiro compartilhado (letras + cores visíveis a todos)."""
    return {
        "type": "shared_grid_update",
        "submission": {
            "player_id": sub.player_id,
            "player_name": sub.player_name,
            "avatar": sub.avatar,
            "letters": sub.letters,
            "colors": sub.colors,
        },
        "delta_score": delta_score,
    }


def msg_termo_solved(player: "Player") -> dict:
    return {"type": "termo_solved", "player_id": player.id, "player_name": player.name}


def msg_termo_reveal(room: "Room") -> dict:
    """REVEAL — único lugar onde a palavra e a dica saem do servidor."""
    tr = room.termo_round
    assert tr is not None
    results = [
        {
            "id": p.id,
            "name": p.name,
            "correct": p.last_correct,
            "score": p.score,
            "avatar": p.avatar,
        }
        for p in room.players.values()
    ]
    msg: dict = {
        "type": "termo_reveal",
        "word": tr.word,
        "theme": tr.theme,
        "hint": tr.hint,
        "results": results,
    }
    if tr.shared_grid:
        msg["shared_grid"] = [
            {
                "player_id": s.player_id,
                "player_name": s.player_name,
                "avatar": s.avatar,
                "letters": s.letters,
                "colors": s.colors,
            }
            for s in tr.shared_grid
        ]
    return msg
