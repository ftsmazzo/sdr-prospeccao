"""Ofertas pendentes: o código executa o 'sim' do lead."""

from __future__ import annotations

import re
from typing import Any, Literal

OfferType = Literal["contrato", "encaminhamento", "resumo"]

_AFFIRM_RE = re.compile(
    r"(?i)\b("
    r"sim\b|pode\b|gostaria|adoraria|quero|bora|fechado|manda\b"
    r"|faz\s+isso|faz\s+aí|faz\s+ai"
    r"|registra(?:r)?|anota(?:r)?|encaminha(?:r)?"
    r"|manda(?:r)?|envie|envia|manda\s+sim|pode\s+sim"
    r"|claro|isso|beleza|ok\b|pode\s+ser|pode\s+mandar"
    r"|me\s+envia|me\s+manda|quero\s+sim|vamos"
    r")\b"
)

_REFUSE_OFFER_RE = re.compile(
    r"(?i)\b("
    r"n[aã]o\s+quero\s+(?:contrato|especialista|registro|agora|mais)"
    r"|n[aã]o\s+(?:precisa|agora)"
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

_RELACAO_PATTERNS: tuple[tuple[re.Pattern[str], str, str], ...] = (
    (re.compile(r"(?i)\bminha\s+esposa\b|\besposa\b"), "esposa", "f"),
    (re.compile(r"(?i)\bmeu\s+marido\b|\bmarido\b"), "marido", "m"),
    (re.compile(r"(?i)\bminha\s+filha\b"), "filha", "f"),
    (re.compile(r"(?i)\bmeu\s+filho\b"), "filho", "m"),
    (re.compile(r"(?i)\bpra\s+ela\b|\bpara\s+ela\b|\bela\b"), "ela", "f"),
    (re.compile(r"(?i)\bpra\s+ele\b|\bpara\s+ele\b"), "ele", "m"),
)

_NEW_PURCHASE_RE = re.compile(
    r"(?i)\b("
    r"outra\s+p[oó]s|outro\s+curso|mais\s+uma\s+matr[ií]cula"
    r"|quero\s+(?:fazer|matricular|uma\s+p[oó]s)"
    r"|sim\s+quero|quero\s+sim"
    r"|para\s+(?:minha|meu)\s+(?:esposa|marido|filha|filho)"
    r"|pra\s+(?:minha|meu)\s+(?:esposa|marido|filha|filho)"
    r"|interessad[oa]\s+em\s+(?:outra|outro)"
    r"|curso\s+para\s+(?:minha|meu|ela|ele)"
    r")\b"
)


def lead_affirms_offer(text: str) -> bool:
    """Reserva lexical — preferir resposta_a_oferta do modelo."""
    if lead_refuses_offer(text):
        return False
    return bool(_AFFIRM_RE.search(text or ""))


def classify_offer_response_fallback(text: str) -> str | None:
    """Fallback lexical: aceitou | recusou | None (indefinido)."""
    if lead_refuses_offer(text):
        return "recusou"
    if lead_affirms_offer(text):
        return "aceitou"
    return None


def lead_refuses_offer(text: str) -> bool:
    # "não quero" sozinho / recusa de oferta — não confundir com "Sim quero"
    t = text or ""
    if re.search(r"(?i)\bsim\b.*\bquero\b|\bquero\s+sim\b", t):
        return False
    return bool(_REFUSE_OFFER_RE.search(t))


def detect_third_person_student(text: str) -> bool:
    return bool(_THIRD_PERSON_RE.search(text or ""))


def detect_aluno_relacao(text: str) -> tuple[str | None, str | None]:
    """Retorna (relacao, genero 'f'|'m')."""
    for rx, rel, gen in _RELACAO_PATTERNS:
        if rx.search(text or ""):
            return rel, gen
    return None, None


def apply_third_person_flags(ls: dict[str, Any], text: str) -> None:
    if not detect_third_person_student(text):
        return
    ls["aluno_e_terceiro"] = True
    rel, gen = detect_aluno_relacao(text)
    if rel:
        ls["aluno_relacao"] = rel
    if gen:
        ls["aluno_genero"] = gen


def lead_wants_new_purchase(text: str) -> bool:
    return bool(_NEW_PURCHASE_RE.search(text or "")) or detect_third_person_student(
        text or ""
    )


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


_OFFER_CONTRATO_RE = re.compile(
    r"(?i)\b("
    r"(?:quero|posso|quer)\s+(?:que\s+(?:eu\s+)?)?(?:enviar|mandar|gerar|preparar)"
    r"\s+(?:o\s+)?contrato"
    r"|envi(?:ar|e|o)\s+(?:o\s+)?contrato"
    r"|gerar\s+(?:o\s+)?contrato"
    r"|manda(?:r)?\s+(?:o\s+)?contrato"
    r"|(?:preparar|gerar|seguir\s+com|fechar)\s+(?:a\s+)?matr[ií]cula"
    r"|quer\s+(?:que\s+(?:eu\s+)?)?(?:prepare|gere|mande)\s+(?:o\s+)?contrato"
    r"|quer\s+seguir\s+com\s+a\s+matr[ií]cula"
    r")\b"
)
_OFFER_HANDOFF_RE = re.compile(
    r"(?i)\b("
    r"(?:quero|posso|quer)\s+(?:que\s+(?:eu\s+)?)?(?:registrar|anotar|encaminhar)"
    r"|registrar?\s+(?:seu|o)\s+pedido"
    r"|encaminhar\s+(?:para\s+)?(?:um\s+)?especialista"
    r"|especialista\s+(?:do\s+polo\s+)?(?:te\s+)?(?:ajuda|fala|chama)"
    r"|quer\s+que\s+eu\s+registre"
    r")\b"
)
_OFFER_RESUMO_RE = re.compile(
    r"(?i)\b("
    r"(?:quero|posso|quer)\s+(?:que\s+(?:eu\s+)?)?(?:te\s+)?(?:mandar|enviar|passar)\s+"
    r"(?:um\s+)?resumo"
    r"|te\s+mando\s+(?:um\s+)?resumo"
    r"|mandar\s+(?:um\s+)?resumo"
    r"|quer\s+(?:um\s+)?resumo"
    r")\b"
)
def infer_offer_from_reply(reply: str) -> dict[str, Any] | None:
    """Se a reply oferece algo executável e o modelo omitiu offer."""
    text = reply or ""
    if _OFFER_CONTRATO_RE.search(text):
        return {"type": "contrato"}
    if _OFFER_HANDOFF_RE.search(text):
        return {"type": "encaminhamento", "motivo": "especialista"}
    if _OFFER_RESUMO_RE.search(text):
        return {"type": "resumo"}
    return None


_ASKS_REGISTERED_RE = re.compile(
    r"(?i)\b("
    r"(?:voc[eê]|vc)\s+registrou"
    r"|registrou\s*\?"
    r"|j[aá]\s+registrou"
    r"|foi\s+registrado"
    r"|anotou\s*\?"
    r")\b"
)


def lead_asks_if_registered(text: str) -> bool:
    return bool(_ASKS_REGISTERED_RE.search(text or ""))


def contract_data_request_reply(meta: dict[str, Any], ls: dict[str, Any]) -> str:
    """Pede só o que falta para gerar o contrato (gênero resolvido)."""
    third = bool(ls.get("aluno_e_terceiro"))
    aluno = (ls.get("aluno_nome") or "").strip()
    rel = (ls.get("aluno_relacao") or "").strip().casefold()
    gen = (ls.get("aluno_genero") or "").strip().casefold()

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

    if not third and not aluno:
        return (
            f"Perfeito! Pra eu gerar o contrato, me passa o {need} seu. "
            "Você lê o contrato com calma antes de confirmar qualquer pagamento."
        )

    # Terceiro / nome do aluno
    if aluno:
        whose_pronoun = "dela" if gen == "f" else ("dele" if gen == "m" else "")
        if whose_pronoun:
            return (
                f"Perfeito! Pra eu gerar o contrato de {aluno}, me passa o {need} "
                f"{whose_pronoun}. Você lê o contrato com calma antes de confirmar "
                "qualquer pagamento."
            )
        return (
            f"Perfeito! Pra eu gerar o contrato de {aluno}, me passa o {need} "
            "da pessoa que vai estudar. Você lê o contrato com calma antes de "
            "confirmar qualquer pagamento."
        )

    if rel in ("esposa", "filha") or gen == "f":
        label = "da sua esposa" if rel == "esposa" else (
            "da sua filha" if rel == "filha" else "dela"
        )
        return (
            f"Perfeito! Pra eu gerar o contrato {label}, me passa o {need} dela. "
            "Você lê o contrato com calma antes de confirmar qualquer pagamento."
        )
    if rel in ("marido", "filho") or gen == "m":
        label = "do seu marido" if rel == "marido" else (
            "do seu filho" if rel == "filho" else "dele"
        )
        return (
            f"Perfeito! Pra eu gerar o contrato {label}, me passa o {need} dele. "
            "Você lê o contrato com calma antes de confirmar qualquer pagamento."
        )
    return (
        f"Perfeito! Pra eu gerar o contrato da pessoa que vai estudar, me passa "
        f"o {need}. Você lê o contrato com calma antes de confirmar qualquer pagamento."
    )


def missing_contract_fields(meta: dict[str, Any], ls: dict[str, Any]) -> list[str]:
    missing: list[str] = []
    # Para terceiro, nome do aluno pode estar em aluno_nome; full_name/meta.nome é comprador
    if ls.get("aluno_e_terceiro"):
        if not (ls.get("aluno_nome") or meta.get("full_name")):
            missing.append("nome completo")
    elif not (meta.get("full_name") or ls.get("nome")):
        missing.append("nome completo")
    if not meta.get("cpf"):
        missing.append("CPF")
    if not meta.get("birth_date"):
        missing.append("data de nascimento")
    return missing
