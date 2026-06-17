"""Pontuação e normalização."""
from app.game.scoring import MAX_POINTS, compute_score, normalize


def test_score_instantaneo_vale_o_maximo():
    assert compute_score(0.0, 20.0) == MAX_POINTS


def test_score_no_estouro_do_tempo_vale_o_piso():
    assert compute_score(20.0, 20.0) == round(MAX_POINTS * 0.5)
    assert compute_score(40.0, 20.0) == round(MAX_POINTS * 0.5)


def test_mais_rapido_pontua_mais():
    rapido = compute_score(2.0, 20.0)
    lento = compute_score(15.0, 20.0)
    assert rapido > lento


def test_normalize_remove_acentos_maiusculas_e_pontuacao():
    assert normalize("Pokémon: Pikachu!") == "pokemon pikachu"
    assert normalize("  Águia   Real  ") == "aguia real"
    assert normalize("Nidoran-M") == "nidoran m"


def test_normalize_string_vazia():
    assert normalize("") == ""
    assert normalize("   ") == ""
