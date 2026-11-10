"""Valores e horas por extenso para TTS (sem API)."""

from __future__ import annotations

from app.money_speech import (
    all_table_amounts,
    brl_amount_to_spoken,
    expand_money_and_hours_for_speech,
    hours_to_spoken,
)
from app.pricing import BAND_620_750, BAND_880_1000, BAND_ATE_520
from app.speech import phonetize_for_tts


def test_brl_known_examples():
    assert brl_amount_to_spoken("79,90") == "setenta e nove reais e noventa centavos"
    assert brl_amount_to_spoken("1.438,20") == (
        "mil quatrocentos e trinta e oito reais e vinte centavos"
    )
    assert brl_amount_to_spoken("69,90") == "sessenta e nove reais e noventa centavos"


def test_hours_feminine():
    assert hours_to_spoken(750) == "setecentas e cinquenta horas"
    assert hours_to_spoken(1000) == "mil horas"
    assert hours_to_spoken(1) == "uma hora"


def test_all_table_amounts_spoken():
    amounts = all_table_amounts()
    assert set(amounts) >= {
        BAND_ATE_520.monthly,
        BAND_ATE_520.total_18,
        BAND_ATE_520.a_vista,
        BAND_620_750.monthly,
        BAND_620_750.total_18,
        BAND_620_750.a_vista,
        BAND_880_1000.monthly,
        BAND_880_1000.total_18,
        BAND_880_1000.a_vista,
    }
    for amt in amounts:
        spoken = brl_amount_to_spoken(amt)
        assert "reais" in spoken or spoken == "um real"
        assert "vírgula" not in spoken
        assert "," not in spoken


def test_expand_money_and_hours_in_text():
    text = "A mensalidade é R$ 79,90 e a carga é 750h."
    out = expand_money_and_hours_for_speech(text)
    assert "setenta e nove reais e noventa centavos" in out
    assert "setecentas e cinquenta horas" in out
    assert "R$" not in out
    assert "vírgula" not in out


def test_phonetize_expands_money():
    out = phonetize_for_tts("Mensalidade R$ 89,90 na pós de 1000h.")
    assert "oitenta e nove reais e noventa centavos" in out
    assert "mil horas" in out
