"""Escada de desconto demo + saída de handoff."""

from __future__ import annotations

from types import SimpleNamespace

from app.checkout import create_checkout
from app.desconto_negocio import (
    a_vista_com_percentual,
    exit_handoff_to_negociacao,
    ladder_pcts,
    next_desconto_pct,
    pricing_snapshot_for_course,
    register_desconto_offer,
)
from app.documents import build_contrato_pdf
from app.lead_state import advance_etapa, ensure_lead_state
from app.pricing import BAND_620_750


def test_avista_20_and_30():
    # 1438,20 * 0.8 = 1150,56 ; * 0.7 = 1006,74
    assert a_vista_com_percentual(BAND_620_750, 20) == "1.150,56"
    assert a_vista_com_percentual(BAND_620_750, 30) == "1.006,74"


def test_ladder_demo(monkeypatch):
    s = SimpleNamespace(
        demo_negocio_desconto=True,
        desconto_tabela_avista_pct=10,
        desconto_negocio_alvo_pct=20,
        desconto_negocio_max_pct=30,
    )
    monkeypatch.setattr("app.desconto_negocio.get_settings", lambda: s)
    assert ladder_pcts(s) == [10, 20, 30]
    meta: dict = {}
    assert next_desconto_pct(meta, s) == 10
    register_desconto_offer(meta, 10)
    assert next_desconto_pct(meta, s) == 20
    register_desconto_offer(meta, 20)
    assert next_desconto_pct(meta, s) == 30
    register_desconto_offer(meta, 30)
    assert next_desconto_pct(meta, s) is None


def test_advance_second_discount_not_handoff(monkeypatch):
    s = SimpleNamespace(
        demo_negocio_desconto=True,
        desconto_tabela_avista_pct=10,
        desconto_negocio_alvo_pct=20,
        desconto_negocio_max_pct=30,
    )
    monkeypatch.setattr("app.desconto_negocio.get_settings", lambda: s)
    meta: dict = {"desconto_respondido": True, "desconto_negociacao_nivel": 1}
    ls = ensure_lead_state(meta)
    meta["etapa"] = "objecao"
    ls["curso_escolhido"] = "Gestão de Equipes e Gestão da Produção"
    ls["graduacao"] = "concluida"
    ls["perguntou_desconto"] = True
    ls["objecao_ativa"] = "preco"
    meta["lead_state"] = ls
    etapa = advance_etapa(meta)
    assert etapa != "handoff_humano"
    assert meta.get("desconto_oferta_atual_pct") == 20
    assert meta.get("desconto_negociacao_nivel") == 2


def test_exit_handoff_miriely_style():
    meta: dict = {
        "handoff_reason": "desconto_insistencia",
        "etapa_antes_handoff": "objecao",
        "desconto_respondido": True,
        "retomadas_paused": True,
        "handoff_registrado": True,
        "handoff_avisado": True,
        "handoff_request_id": "abc",
    }
    ls = ensure_lead_state(meta)
    ls["nome"] = "Miriely"
    ls["curso_escolhido"] = "Gestão de Equipes e Gestão da Produção"
    meta["lead_state"] = ls
    meta["etapa"] = "handoff_humano"
    etapa = exit_handoff_to_negociacao(meta)
    assert etapa == "objecao"
    assert meta.get("etapa") == "objecao"
    assert meta.get("comercial_retorno") is True
    assert meta.get("handoff_reason") is None
    assert meta.get("retomadas_paused") is False
    assert meta.get("handoff_registrado") is False
    assert meta.get("handoff_avisado") is False
    assert "handoff_request_id" not in meta
    assert int(meta.get("desconto_negociacao_nivel") or 0) >= 1


def test_exit_handoff_rejects_matriculado():
    meta: dict = {
        "etapa": "matriculado",
        "etapa_antes_handoff": "objecao",
        "handoff_reason": "desconto_insistencia",
    }
    try:
        exit_handoff_to_negociacao(meta)
        raise AssertionError("deveria recusar matriculado")
    except ValueError as exc:
        assert "etapa_protegida" in str(exc)
    assert meta["etapa"] == "matriculado"


def test_exit_handoff_rejects_not_in_handoff():
    meta: dict = {"etapa": "objecao"}
    try:
        exit_handoff_to_negociacao(meta)
        raise AssertionError("deveria recusar fora de handoff")
    except ValueError as exc:
        assert "nao_em_handoff" in str(exc)


def test_pricing_snapshot_acordo_20():
    course = "Gestão de Equipes e Gestão da Produção"
    snap = pricing_snapshot_for_course(course, desconto_pct=20)
    assert snap["a_vista"] == "1.150,56"
    assert "20%" in snap["valores_line"]
    assert "acordo" in snap["valores_line"]


def test_checkout_e_pdf_respeitam_acordo_30():
    course = "Gestão de Equipes e Gestão da Produção"
    session = create_checkout(
        "sim:acordo",
        course_label=course,
        lead_name="Miriely",
        desconto_pct=30,
    )
    assert session.desconto_pct == 30
    assert session.a_vista_label == "R$ 1.006,74"
    snap = pricing_snapshot_for_course(course, desconto_pct=30)
    assert "1.006,74" in snap["valores_line"]
    pdf = build_contrato_pdf(lead_name="Miriely", course=course, desconto_pct=30)
    assert pdf.startswith(b"%PDF")


def test_snapshot_sem_faixa_ainda_mostra_pct():
    snap = pricing_snapshot_for_course(
        "Pós-Graduação EAD Faveni", desconto_pct=20
    )
    assert snap["band"] is None
    assert snap["desconto_pct"] == 20
    assert "20%" in snap["valores_line"]
    assert snap["a_vista_label"] is not None
