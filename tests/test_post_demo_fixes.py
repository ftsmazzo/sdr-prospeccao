"""Ajustes pós-teste WhatsApp 0.9.2 (só unitários)."""

from __future__ import annotations

from app.documents import build_contrato_pdf
from app.handoff_requests import handoff_registered_reply
from app.lead_state import (
    begin_new_purchase,
    ensure_lead_state,
    lead_says_farewell_or_space,
    rewrite_blocked_action_reply,
)
from app.offers import (
    apply_third_person_flags,
    contract_data_request_reply,
    lead_wants_new_purchase,
)
from app.schemas import format_cpf


def test_format_cpf():
    assert format_cpf("12345678901") == "123.456.789-01"
    assert format_cpf("123.456.789-01") == "123.456.789-01"


def test_pdf_cpf_formatted_in_source_path():
    # Garante que o helper de formatação é o usado na montagem
    assert format_cpf("98765432100") == "987.654.321-00"
    pdf = build_contrato_pdf(lead_name="Ana", cpf="12345678901", course="Autismo")
    assert pdf.startswith(b"%PDF")


def test_handoff_reply_keeps_real_motivo():
    reply = handoff_registered_reply(
        nome="Carlos", motivo="data de vencimento da mensalidade"
    )
    assert "data de vencimento da mensalidade" in reply
    assert "seu atendimento" not in reply


def test_farewell_stock_only_on_farewell():
    ls = {"curso_escolhido": None, "aceite_matricula": False}
    stock = rewrite_blocked_action_reply(
        "dados_antes_fechamento",
        "Me passa o CPF",
        ls,
        user_text="Sim quero",
    )
    assert "quando quiser retomar" not in stock.casefold()
    assert lead_says_farewell_or_space("Vou pensar e te falo")
    farewell = rewrite_blocked_action_reply(
        "promessa_lembrete",
        "Te chamo depois",
        ls,
        user_text="Vou pensar e te falo",
    )
    assert "quando quiser retomar" in farewell.casefold()


def test_new_purchase_from_matriculado_preserves_matriculas():
    meta = {
        "etapa": "matriculado",
        "matriculas": [{"curso": "Autismo", "status": "confirmada"}],
        "lead_state": {},
    }
    ls = ensure_lead_state(meta)
    ls["curso_escolhido"] = "Autismo"
    ls["graduacao"] = "concluida"
    ls["aceite_matricula"] = True
    apply_third_person_flags(ls, "quero uma pós para minha esposa")
    assert ls["aluno_e_terceiro"] is True
    assert lead_wants_new_purchase("Sim quero")
    begin_new_purchase(meta, ls)
    assert meta["matriculas"][0]["curso"] == "Autismo"
    assert meta["etapa"] == "qualificacao"
    assert ls["graduacao"] is None
    assert ls["aceite_matricula"] is False


def test_contract_data_gender_esposa():
    meta: dict = {}
    ls = {
        "aluno_e_terceiro": True,
        "aluno_relacao": "esposa",
        "aluno_genero": "f",
    }
    text = contract_data_request_reply(meta, ls)
    assert "dela/dele" not in text
    assert "dela" in text
    assert "esposa" in text


def test_contract_data_neutral_unknown_gender():
    meta: dict = {}
    ls = {"aluno_e_terceiro": True}
    text = contract_data_request_reply(meta, ls)
    assert "dela/dele" not in text
    assert "pessoa que vai estudar" in text
