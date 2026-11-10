"""Gera PDF placebo de contrato/informativo de matrícula (demo) com UTF-8."""

from __future__ import annotations

from pathlib import Path

from fpdf import FPDF

from app.pricing import amount_label_for_course, price_for_course

_FONT_CANDIDATES = (
    Path(__file__).resolve().parent.parent / "static" / "fonts" / "DejaVuSans.ttf",
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    Path("C:/Windows/Fonts/arial.ttf"),
)


def _find_font() -> Path | None:
    for p in _FONT_CANDIDATES:
        if p.is_file():
            return p
    return None


def build_contrato_pdf(
    *,
    lead_name: str = "",
    cpf: str = "",
    birth_date: str = "",
    course: str = "Pós-Graduação EAD Faveni",
    agent_name: str = "Clara",
    course_hours: int | None = None,
) -> bytes:
    nome = lead_name.strip() or "Interessado(a)"
    cpf_line = cpf.strip() or "a confirmar"
    nasc = birth_date.strip() or "a confirmar"
    agent = (agent_name or "Clara").strip() or "Clara"
    band = price_for_course(course)
    if band:
        valores = (
            f"Mensalidade {band.monthly_label} · "
            f"Total em 18x {band.total_18_label} · "
            f"À vista {band.a_vista_label}"
        )
    else:
        valores = f"Mensalidade (demo): {amount_label_for_course(course)}"

    hours_line = f"{course_hours}h" if course_hours else "conforme catálogo"

    pdf = FPDF(format="A4")
    pdf.set_margins(20, 20, 20)
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.add_page()
    font_path = _find_font()
    family = "DemoUni"
    if font_path:
        pdf.add_font(family, "", str(font_path))
    else:
        family = "Helvetica"

    def title(text: str) -> None:
        pdf.set_font(family, size=16)
        pdf.set_x(pdf.l_margin)
        pdf.multi_cell(0, 10, text)

    def section(text: str) -> None:
        pdf.ln(2)
        pdf.set_font(family, size=13)
        pdf.set_x(pdf.l_margin)
        pdf.multi_cell(0, 8, text)

    def body(text: str) -> None:
        pdf.set_font(family, size=11)
        pdf.set_x(pdf.l_margin)
        pdf.multi_cell(0, 7, text)

    def small(text: str) -> None:
        pdf.set_font(family, size=9)
        pdf.set_x(pdf.l_margin)
        pdf.multi_cell(0, 6, text)

    title("Faveni Polo Catanduva")
    body("Contrato / Informativo de Matrícula (demonstração)")
    section("1. Aluno")
    body(f"Nome completo: {nome}")
    body(f"CPF: {cpf_line}")
    body(f"Data de nascimento: {nasc}")
    section("2. Curso")
    body(f"Curso: {course}")
    body(f"Carga horária: {hours_line}")
    body("Modalidade: 100% EAD")
    section("3. Valores (demonstração)")
    body(valores)
    body("Sem taxa de matrícula. Primeira mensalidade na confirmação.")
    section("4. Próximos passos")
    body("Confira os dados acima com calma.")
    body(
        "Se estiver tudo certo, confirme a matrícula pelo link que a consultora Clara "
        "enviar em seguida nesta conversa."
    )
    body(
        "Documentos complementares (RG/CNH, diploma ou declaração, histórico e certidão) "
        "podem ser enviados depois da confirmação."
    )
    pdf.ln(4)
    small(
        "Documento de demonstração — sem validade jurídica e sem cobrança. "
        f"Atendimento: consultora {agent}."
    )

    out = pdf.output()
    return bytes(out) if isinstance(out, (bytes, bytearray)) else bytes(out)
