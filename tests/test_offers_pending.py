"""Unitários de pending_offer / inferência (sem API)."""

from __future__ import annotations

from app.offers import (
    contract_data_request_reply,
    infer_offer_from_reply,
    lead_affirms_offer,
    lead_asks_if_registered,
    lead_refuses_offer,
    normalize_offer,
)
from app.lead_state import _stock_variants


def test_infer_contrato_and_handoff():
    assert infer_offer_from_reply("Quer que eu envie o contrato para ela analisar?")["type"] == "contrato"
    assert infer_offer_from_reply("Quer que eu registre seu pedido?")["type"] == "encaminhamento"
    assert infer_offer_from_reply("Posso te mandar um resumo?")["type"] == "resumo"
    assert infer_offer_from_reply("Qual curso você prefere?") is None


def test_affirm_and_refuse():
    assert lead_affirms_offer("Sim")
    assert lead_affirms_offer("Gostaria")
    assert lead_refuses_offer("não quero agora")
    assert not lead_affirms_offer("não quero agora")


def test_asks_registered():
    assert lead_asks_if_registered("Vc registrou?")
    assert lead_asks_if_registered("você registrou?")
    assert not lead_asks_if_registered("quero registrar")


def test_normalize_offer():
    assert normalize_offer({"type": "contrato"}) == {"type": "contrato"}
    assert normalize_offer({"type": "encaminhamento", "motivo": "suporte_aluno"})[
        "motivo"
    ] == "suporte_aluno"
    assert normalize_offer({"type": "x"}) is None


def test_contract_third_person_copy():
    ls = {"aluno_e_terceiro": True, "aluno_nome": None}
    meta: dict = {}
    text = contract_data_request_reply(meta, ls)
    assert "dela/dele" in text
    assert "nome completo" in text


def test_stock_acao_fingida_not_farewell():
    variants = _stock_variants("acao_fingida", {"curso_escolhido": "Autismo"})
    assert variants
    assert all("retomar" not in v.casefold() for v in variants)
    assert any("registre" in v.casefold() for v in variants)
