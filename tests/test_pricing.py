"""Tabela de preços por carga horária."""

from __future__ import annotations

from app.checkout import create_checkout
from app.documents import build_contrato_pdf
from app.pricing import (
    amount_label_for_course,
    band_for_hours,
    lookup_course_hours,
    price_for_course,
)


def test_faixas_por_carga():
    assert band_for_hours(420).monthly == "69,90"
    assert band_for_hours(520).monthly == "69,90"
    assert band_for_hours(620).monthly == "79,90"
    assert band_for_hours(750).monthly == "79,90"
    assert band_for_hours(880).monthly == "89,90"
    assert band_for_hours(1000).monthly == "89,90"


def test_curso_catalogo_resolve_faixa():
    assert lookup_course_hours("Psicopedagogia Institucional e Clínica") == 620
    band = price_for_course("Psicopedagogia Institucional e Clínica")
    assert band is not None
    assert band.monthly_label == "R$ 79,90"
    assert band.a_vista_label == "R$ 1.294,38"

    assert price_for_course("Inteligência Artificial para Negócios").monthly == "79,90"
    assert price_for_course("Alfabetização e Letramento").monthly == "69,90"
    assert price_for_course("Autismo").monthly == "89,90"


def test_checkout_e_pdf_usam_faixa():
    from app.desconto_negocio import pricing_snapshot_for_course

    course = "Psicopedagogia Institucional e Clínica"
    session = create_checkout("sim:x", course_label=course, lead_name="Juliana")
    assert session.amount_label == "R$ 79,90"
    assert session.a_vista_label == "R$ 1.294,38"

    snap = pricing_snapshot_for_course(course)
    assert "79,90" in snap["valores_line"]
    pdf = build_contrato_pdf(lead_name="Juliana", course=course)
    assert pdf.startswith(b"%PDF")
    assert amount_label_for_course(None) == "a partir de R$ 69,90"
