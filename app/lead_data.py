"""Extração de dados pessoais do texto do lead (contrato)."""

from __future__ import annotations

import re
from typing import Any

from app.schemas import normalize_cpf

_CPF_RE = re.compile(
    r"(?i)(?:\bcpf\b\s*[:.]?\s*)?(\d{3}\.?\d{3}\.?\d{3}-?\d{2})\b"
)
_BIRTH_RE = re.compile(
    r"(?i)(?:\b(?:nasc(?:imento)?|data(?:\s+de\s+nasc(?:imento)?)?)\b\s*[:.]?\s*)?"
    r"(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})\b"
)
# Nome: linha/"nome:" + 2–5 palavras capitalizadas ou título simples
_NAME_LABELED_RE = re.compile(
    r"(?i)\bnome(?:\s+completo)?\s*[:\-]\s*([A-Za-zÁ-ú][A-Za-zÁ-ú'\-]+"
    r"(?:\s+[A-Za-zÁ-ú][A-Za-zÁ-ú'\-]+){1,4})"
)
_NAME_LINE_RE = re.compile(
    r"(?m)^([A-Za-zÁ-ú][A-Za-zÁ-ú'\-]+(?:\s+[A-Za-zÁ-ú][A-Za-zÁ-ú'\-]+){1,4})\s*$"
)


def _norm_birth(raw: str) -> str:
    parts = re.split(r"[/-]", raw.strip())
    if len(parts) != 3:
        return raw.strip()
    d, m, y = parts
    if len(y) == 2:
        y = ("20" + y) if int(y) < 50 else ("19" + y)
    return f"{int(d):02d}/{int(m):02d}/{y}"


def extract_contract_fields_from_text(text: str) -> dict[str, str]:
    """Extrai o que houver de nome/CPF/nascimento no texto do lead."""
    out: dict[str, str] = {}
    raw = text or ""

    m_cpf = _CPF_RE.search(raw)
    if m_cpf:
        cpf = normalize_cpf(m_cpf.group(1))
        if cpf:
            out["cpf"] = cpf

    m_birth = _BIRTH_RE.search(raw)
    if m_birth:
        out["birth_date"] = _norm_birth(m_birth.group(1))

    m_name = _NAME_LABELED_RE.search(raw)
    if m_name:
        out["full_name"] = re.sub(r"\s+", " ", m_name.group(1)).strip()
    else:
        # Se a mensagem tem CPF/nascimento, tenta a 1ª linha só com nome
        if out.get("cpf") or out.get("birth_date"):
            for line in raw.splitlines():
                line = line.strip()
                if not line or _CPF_RE.search(line) or _BIRTH_RE.search(line):
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
    """Grava no meta/ls sem apagar o que já existia."""
    if extracted.get("cpf") and not meta.get("cpf"):
        meta["cpf"] = extracted["cpf"]
    if extracted.get("birth_date") and not meta.get("birth_date"):
        meta["birth_date"] = extracted["birth_date"]
    if extracted.get("full_name"):
        name = extracted["full_name"]
        if ls.get("aluno_e_terceiro"):
            if not ls.get("aluno_nome"):
                ls["aluno_nome"] = name
            if not meta.get("full_name"):
                meta["full_name"] = name
        else:
            if not meta.get("full_name"):
                meta["full_name"] = name
            if not ls.get("nome"):
                ls["nome"] = name
    meta["lead_state"] = ls
