"""Ofertas pendentes: o código executa o 'sim' do lead."""

from __future__ import annotations

import re
from typing import Any, Literal

OfferType = Literal["contrato", "encaminhamento", "resumo"]

_AFFIRM_RE = re.compile(
    r"(?i)\b("
    r"sim\b|pode\b|gostaria|quero|faz\s+isso|faz\s+aí|faz\s+ai"
    r"|registra(?:r)?|anota(?:r)?|encaminha(?:r)?"
    r"|manda(?:r)?|envie|envia|manda\s+sim|pode\s+sim"
    r"|claro|isso|beleza|ok\b|pode\s+ser|pode\s+mandar"
    r"|me\s+envia|me\s+manda"
    r")\b"
)

_REFUSE_OFFER_RE = re.compile(
    r"(?i)\b("
    r"n[aã]o\s+quero\s+(?:contrato|especialista|registro|agora|mais)"
    r"|n[aã]o\s+(?:precisa|agora|quero)"
    r"|depois\b|deixa\s+pra\s+l[aá]|sem\s+intermedi[aá]rio"
    r"|n[aã]o\s+envie|n[aã]o\s+manda"
    r")\b"
)

_THIRD_PERSON_RE = re.compile(
    r"(?i)\b("
    r"minha\s+esposa|meu\s+marido|minha\s+filha|meu\s+filho"
    r"|para\s+(?:ela|ele)|pra\s+(?:ela|ele)"
    r"|ela\s+(?:quer|vai|precisa|est[aá])"
    r"|ele\s+(?:quer|vai|precisa|est[aá])"
    r"|esposa|marido"
    r")\b"
)


def lead_affirms_offer(text: str) -> bool:
    if lead_refuses_offer(text):
        return False
    return bool(_AFFIRM_RE.search(text or ""))


def lead_refuses_offer(text: str) -> bool:
    return bool(_REFUSE_OFFER_RE.search(text or ""))


def detect_third_person_student(text: str) -> bool:
    return bool(_THIRD_PERSON_RE.search(text or ""))


def normalize_offer(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    t = str(raw.get("type") or "").strip().casefold()
    if t not in ("contrato", "encaminhamento", "resumo"):
        return None
    out: dict[str, Any] = {"type": t}
    motivo = raw.get("motivo")
    if motivo:
        out["motivo"] = str(motivo).strip()[:120]
    return out


def contract_data_request_reply(meta: dict[str, Any], ls: dict[str, Any]) -> str:
    """Pede só o que falta para gerar o contrato."""
    third = bool(ls.get("aluno_e_terceiro"))
    aluno = (ls.get("aluno_nome") or "").strip()
    if aluno:
        whose = f"de {aluno}"
    elif third:
        whose = "dela/dele (da pessoa que vai estudar)"
    else:
        whose = "seu"
    missing = missing_contract_fields(meta, ls) or [
        "nome completo",
        "CPF",
        "data de nascimento",
    ]
    if len(missing) == 1:
        need = missing[0]
    elif len(missing) == 2:
        need = f"{missing[0]} e {missing[1]}"
    else:
        need = f"{missing[0]}, {missing[1]} e {missing[2]}"
    return (
        f"Perfeito! Pra eu gerar o contrato, me passa o {need} {whose}. "
        "Você lê o contrato com calma antes de confirmar qualquer pagamento."
    )


def missing_contract_fields(meta: dict[str, Any], ls: dict[str, Any]) -> list[str]:
    missing: list[str] = []
    if not (meta.get("full_name") or ls.get("nome")):
        missing.append("nome completo")
    if not meta.get("cpf"):
        missing.append("CPF")
    if not meta.get("birth_date"):
        missing.append("data de nascimento")
    return missing
