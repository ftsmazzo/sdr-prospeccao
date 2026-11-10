"""Esquiva vaga não vaza 'modo demo' e não abandona o lead."""

from __future__ import annotations

from app.lead_state import (
    lead_asks_explicit_callback,
    lead_says_farewell_or_space,
    lead_soft_deferral,
    reply_looks_lazy_close,
    soft_deferral_probe_reply,
)


def test_soft_deferral_detects_vague_moment():
    text = "Não. Vou esperar um momento melhor. Agora não tenho como fazer!"
    assert lead_soft_deferral(text)
    assert not lead_asks_explicit_callback(text)
    assert not lead_says_farewell_or_space(text)


def test_lazy_close_without_question():
    lazy = (
        "Sem problemas, Frederico! Quando o momento fizer mais sentido pra você, "
        "é só me chamar aqui que seguimos com a matrícula."
    )
    assert reply_looks_lazy_close(lazy)
    probe = soft_deferral_probe_reply("Frederico")
    assert "?" in probe
    assert "modo demo" not in probe.casefold()
    assert not reply_looks_lazy_close(probe)


def test_explicit_callback_requires_intent():
    assert lead_asks_explicit_callback("Me chama semana que vem")
    assert lead_asks_explicit_callback("Me cobra depois")
    assert not lead_asks_explicit_callback("agora não posso")
    assert not lead_asks_explicit_callback("amanhã tenho prova")
    assert not lead_asks_explicit_callback("como você me chama?")


def test_soft_deferral_avoids_false_positives():
    assert not lead_soft_deferral("agora não sei o curso")
    assert not lead_soft_deferral("não tenho como saber")
    assert not lead_soft_deferral("por enquanto trabalho de noite")
    assert lead_soft_deferral("agora não posso fazer")
    assert lead_soft_deferral("não tenho como pagar agora")


def test_farewell_with_tchau_not_blocked_by_soft_only():
    text = "tchau, até mais"
    assert lead_says_farewell_or_space(text)
    assert not lead_soft_deferral(text)


def test_soft_decline_is_not_explicit_callback():
    """Abandonar o momento ≠ pedir para a Clara remarcar."""
    text = "Não. Vou esperar um momento melhor. Agora não tenho como fazer!"
    assert lead_soft_deferral(text)
    assert not lead_asks_explicit_callback(text)
