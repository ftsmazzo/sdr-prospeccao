"""Extração de dados pessoais do texto do lead (contrato)."""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from app.contract_party import is_third_person_purchase, store_aluno_dados
from app.schemas import normalize_cpf

_CPF_RE = re.compile(
    r"(?i)(?:\bcpf\b\s*[:.]?\s*)?(\d{3}\.?\d{3}\.?\d{3}-?\d{2})\b"
)
_BIRTH_LABELED_RE = re.compile(
    r"(?i)\b(?:nasc(?:imento)?|data(?:\s+de\s+nasc(?:imento)?)?)\b\s*[:.]?\s*"
    r"(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})\b"
)
_DATE_ONLY_RE = re.compile(r"\b(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})\b")
_NAME_LABELED_RE = re.compile(
    r"(?i)\bnome(?:\s+completo)?\s*[:\-]\s*([A-Za-zÁ-ú][A-Za-zÁ-ú'\-]+"
    r"(?:\s+[A-Za-zÁ-ú][A-Za-zÁ-ú'\-]+){1,4})"
)
_NAME_LINE_RE = re.compile(
    r"(?m)^([A-Za-zÁ-ú][A-Za-zÁ-ú'\-]+(?:\s+[A-Za-zÁ-ú][A-Za-zÁ-ú'\-]+){1,4})\s*$"
)


def _norm_birth(raw: str) -> str | None:
    parts = re.split(r"[/-]", raw.strip())
    if len(parts) != 3:
        return None
    try:
        d, m, y = (int(parts[0]), int(parts[1]), int(parts[2]))
    except ValueError:
        return None
    if y < 100:
        y = (2000 + y) if y < 50 else (1900 + y)
    if not (1 <= d <= 31 and 1 <= m <= 12):
        return None
    today = date.today()
    try:
        born = date(y, m, d)
    except ValueError:
        return None
    age = today.year - born.year - (
        (today.month, today.day) < (born.month, born.day)
    )
    if age < 15 or age > 90:
        return None
    return f"{d:02d}/{m:02d}/{y}"


def extract_contract_fields_from_text(text: str) -> dict[str, str]:
    """Extrai o que houver de nome/CPF/nascimento no texto do lead."""
    out: dict[str, str] = {}
    raw = text or ""

    m_cpf = _CPF_RE.search(raw)
    if m_cpf:
        cpf = normalize_cpf(m_cpf.group(1))
        if cpf:
            out["cpf"] = cpf

    m_birth = _BIRTH_LABELED_RE.search(raw)
    if m_birth:
        norm = _norm_birth(m_birth.group(1))
        if norm:
            out["birth_date"] = norm
    elif out.get("cpf"):
        for m_date in _DATE_ONLY_RE.finditer(raw):
            norm = _norm_birth(m_date.group(1))
            if norm:
                out["birth_date"] = norm
                break

    m_name = _NAME_LABELED_RE.search(raw)
    if m_name:
        out["full_name"] = re.sub(r"\s+", " ", m_name.group(1)).strip()
    else:
        if out.get("cpf") or out.get("birth_date"):
            for line in raw.splitlines():
                line = line.strip()
                if not line or _CPF_RE.search(line) or _DATE_ONLY_RE.search(line):
                    continue
                if re.search(r"(?i)\b(cpf|nasc|data)\b", line):
                    continue
                m_line = _NAME_LINE_RE.match(line)
                if m_line and len(m_line.group(1).split()) >= 2:
                    out["full_name"] = m_line.group(1).strip()
                    break

    return out


def apply_extracted_contract_fields(
    meta: dict[str, Any], ls: dict[str, Any], extracted: dict[str, str]
) -> None:
    """Grava no meta/ls/compra_atual sem apagar matrícula anterior do comprador."""
    third = is_third_person_purchase(meta, ls)
    nome = extracted.get("full_name")
    cpf = extracted.get("cpf")
    birth = extracted.get("birth_date")

    if third:
        # Dados desta compra vão para o ALUNO — não sobrescrevem cpf/nome do comprador.
        store_aluno_dados(
            meta,
            ls,
            nome=nome or None,
            cpf=cpf or None,
            birth_date=birth or None,
        )
    else:
        if cpf and not meta.get("cpf"):
            meta["cpf"] = cpf
        if birth and not meta.get("birth_date"):
            meta["birth_date"] = birth
        if nome:
            if not meta.get("full_name"):
                meta["full_name"] = nome
            if not ls.get("nome"):
                ls["nome"] = nome
        # Espelha também em aluno_dados da compra própria (mesma pessoa).
        store_aluno_dados(
            meta,
            ls,
            nome=nome or meta.get("full_name") or ls.get("nome"),
            cpf=cpf or meta.get("cpf"),
            birth_date=birth or meta.get("birth_date"),
        )
    meta["lead_state"] = ls
