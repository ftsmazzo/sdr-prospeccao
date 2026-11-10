"""Fatos canônicos de curso + validador."""

from __future__ import annotations

from app.course_facts import (
    course_facts,
    min_months_for_hours,
    reply_has_wrong_course_facts,
    stock_reply_from_facts,
)
from app.handoff_requests import clear_handoff_requests, list_handoff_requests, register_handoff_request
from app.orchestrator import reply_has_scarcity
from app.veracity import claims_unbacked_action, reply_has_markdown_list


def test_psicopedagogia_620():
    f = course_facts("Psicopedagogia Institucional e Clínica")
    assert f is not None
    assert f.hours == 620
    assert f.min_months == 6
    assert f.monthly == "79,90"


def test_educacao_especial_min_10():
    f = course_facts("Educação Especial e Inclusiva")
    assert f is not None
    assert f.hours == 1000
    assert f.min_months == 10
    assert min_months_for_hours(1000) == 10


def test_wrong_hours_detected():
    text = (
        "A pós em Psicopedagogia Institucional e Clínica tem 750 horas "
        "e mensalidade de R$ 79,90."
    )
    assert reply_has_wrong_course_facts(text)


def test_wrong_min_months_1000h():
    text = (
        "A Educação Especial e Inclusiva tem 1000 horas e pode ser concluída "
        "a partir de 6 meses."
    )
    assert reply_has_wrong_course_facts(text)


def test_correct_facts_ok():
    text = (
        "Psicopedagogia Institucional e Clínica tem 620h, a partir de 6 meses, "
        "mensalidade R$ 79,90."
    )
    assert reply_has_wrong_course_facts(text) is None


def test_stock_reply_from_facts_sem_meta():
    ls = {"curso_escolhido": "Psicopedagogia Institucional e Clínica"}
    text = stock_reply_from_facts(ls)
    assert text is not None
    assert "620" in text
    assert "79,90" in text
    low = text.casefold()
    for banned in ("catálogo", "catalogo", "tabela", "dados oficiais", "regras"):
        assert banned not in low


def test_handoff_idempotent():
    clear_handoff_requests()
    a = register_handoff_request(
        phone="5511999", nome="Ana", motivo="uti", curso=None
    )
    b = register_handoff_request(
        phone="5511999", nome="Ana Silva", motivo="uti", curso="UTI"
    )
    assert a["id"] == b["id"]
    assert b["curso"] == "UTI"
    assert len(list_handoff_requests()) == 1
    clear_handoff_requests()


def test_registrei_so_no_turno():
    assert (
        claims_unbacked_action("Registrei seu pedido; um especialista vai falar.")
        == "registro_sem_acao"
    )
    assert (
        claims_unbacked_action(
            "Registrei seu pedido; um especialista vai falar.",
            handoff_registered_this_turn=True,
        )
        is None
    )


def test_vou_verificar_sempre_fingido():
    assert (
        claims_unbacked_action(
            "Vou verificar com o especialista sobre UTI.",
            handoff_registered_this_turn=True,
            handoff_registrado=True,
        )
        == "especialista_sem_acao"
    )


def test_scarcity_garante_garanta():
    assert reply_has_scarcity("Isso garante sua vaga hoje")
    assert reply_has_scarcity("Garanta sua vaga agora")


def test_lista_markdown():
    assert reply_has_markdown_list("- item um\n- item dois")
    assert not reply_has_markdown_list("Texto corrido sem marcadores.")
