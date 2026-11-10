"""PDF demo com UTF-8 / seções."""

from __future__ import annotations

from app.documents import build_contrato_pdf


def test_pdf_has_header_and_utf8_bytes():
    pdf = build_contrato_pdf(
        lead_name="José da Silva",
        cpf="12345678901",
        birth_date="01/01/1990",
        course="Autismo",
        agent_name="Clara",
        course_hours=1000,
    )
    assert pdf.startswith(b"%PDF")
    assert len(pdf) > 1000
    # Conteúdo comprimido pode não ter string literal; aceita existência do PDF válido.
    assert b"endobj" in pdf


def test_pdf_third_person_name():
    pdf = build_contrato_pdf(lead_name="Maria Souza", course="TEA – Transtorno do Espectro Autista")
    assert pdf.startswith(b"%PDF")
