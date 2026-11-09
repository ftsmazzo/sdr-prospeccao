"""Gera PDF placebo de contrato/informativo de matrícula (demo)."""

from __future__ import annotations


def build_contrato_pdf(*, lead_name: str = "", course: str = "Pós-Graduação EAD Faveni") -> bytes:
    nome = lead_name.strip() or "Interessado(a)"
    lines = [
        "FAVENI POLO CATANDUVA — DOCUMENTO DEMO",
        "Contrato / Informativo de Matricula (simulacao)",
        "",
        f"Interessado: {nome}",
        f"Curso: {course}",
        "Modalidade: EAD",
        "Mensalidade referencia (demo): a partir de R$ 69,90",
        "",
        "Este PDF e apenas demonstracao do agente Edu.",
        "Nao possui validade juridica e nao gera cobranca.",
        "Apos o fechamento comercial, o polo envia o contrato oficial.",
        "",
        "Proximo passo sugerido: confirmar interesse e seguir com a matricula.",
    ]
    return _simple_pdf(lines)


def _simple_pdf(lines: list[str]) -> bytes:
    # PDF mínimo (Latin-1) — sem dependências extras
    content_lines = ["BT", "/F1 11 Tf", "50 780 Td", "14 TL"]
    first = True
    for line in lines:
        safe = line.encode("latin-1", errors="replace").decode("latin-1")
        safe = safe.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        if first:
            content_lines.append(f"({safe}) Tj")
            first = False
        else:
            content_lines.append("T*")
            content_lines.append(f"({safe}) Tj")
    content_lines.append("ET")
    stream = "\n".join(content_lines).encode("latin-1")

    objs: list[bytes] = []
    objs.append(b"1 0 obj<< /Type /Catalog /Pages 2 0 R >>endobj\n")
    objs.append(b"2 0 obj<< /Type /Pages /Kids [3 0 R] /Count 1 >>endobj\n")
    objs.append(
        b"3 0 obj<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Contents 4 0 R /Resources<< /Font<< /F1 5 0 R >> >> >>endobj\n"
    )
    objs.append(b"4 0 obj<< /Length " + str(len(stream)).encode() + b" >>stream\n" + stream + b"\nendstream endobj\n")
    objs.append(b"5 0 obj<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>endobj\n")

    out = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for obj in objs:
        offsets.append(len(out))
        out.extend(obj)
    xref_pos = len(out)
    out.extend(f"xref\n0 {len(offsets)}\n".encode())
    out.extend(b"0000000000 65535 f \n")
    for off in offsets[1:]:
        out.extend(f"{off:010d} 00000 n \n".encode())
    out.extend(
        f"trailer<< /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{xref_pos}\n%%EOF\n".encode()
    )
    return bytes(out)
