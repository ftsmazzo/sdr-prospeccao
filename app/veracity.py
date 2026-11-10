"""Detectores de veracidade: ações fingidas, preço inventado, intenção de matrícula."""

from __future__ import annotations

import re
from typing import Any

from app.pricing import allowed_money_amounts

_PRICE_RE = re.compile(r"R\$\s*([\d.]+,\d{2})", re.IGNORECASE)

# Afirma ter recebido mídia/documento agora.
_RECEIVED_DOC_RE = re.compile(
    r"(?i)\b("
    r"recebi\s+(?:seu|sua|o|a|os|as)?\s*(?:rg|cnh|cpf|diploma|hist[oó]rico|"
    r"documento|foto|imagem|arquivo|pdf|comprovante)"
    r"|j[aá]\s+(?:recebi|tenho)\s+(?:seu|sua|o|a)?\s*(?:rg|cnh|cpf|diploma|"
    r"documento|foto)"
    r"|seu\s+(?:rg|documento|foto)\s+(?:chegou|foi\s+recebido)"
    r")"
)

# Consulta/confirmação com polo ou base que não existe no código.
_FAKE_CONFIRM_RE = re.compile(
    r"(?i)\b("
    r"confirmei\s+com\s+(?:o\s+)?polo"
    r"|verifiquei\s+(?:com\s+(?:o\s+)?polo|aqui|no\s+sistema|na\s+base)"
    r"|consultei\s+(?:o\s+)?(?:polo|sistema|base|cat[aá]logo)"
    r"|j[aá]\s+falei\s+com\s+(?:o\s+)?(?:polo|especialista|equipe)"
    r"|falei\s+com\s+(?:o\s+)?(?:polo|especialista)"
    r"|pedi\s+(?:confirma[cç][aã]o|ao\s+polo)"
    r"|o\s+polo\s+(?:me\s+)?confirmou"
    r")"
)

# Encaminhamento / reforço com especialista.
_HANDOFF_CLAIM_RE = re.compile(
    r"(?i)\b("
    r"vou\s+refor[cç]ar"
    r"|encaminhei"
    r"|j[aá]\s+encaminhei"
    r"|vou\s+encaminhar"
    r"|pedi\s+pra\s+(?:um\s+)?especialista"
    r"|especialista\s+(?:vai|do\s+polo)\s+(?:te\s+)?(?:ajudar|retomar|entrar)"
    r"|algu[eé]m\s+(?:do\s+polo\s+)?(?:vai|retoma)"
    r")"
)

# Oferece matrícula / passo a passo.
_OFFERS_ENROLLMENT_RE = re.compile(
    r"(?i)\b("
    r"passo\s+a\s+passo\s+da\s+matr[ií]cula"
    r"|seguir\s+com\s+a\s+matr[ií]cula"
    r"|processo\s+de\s+matr[ií]cula"
    r"|condi[cç][oõ]es\s+para\s+matr[ií]cula"
    r"|quero\s+matricular"
    r"|fazer\s+a\s+matr[ií]cula"
    r"|iniciar\s+a\s+matr[ií]cula"
    r")"
)

# Lead pede matrícula / passo a passo.
_LEAD_ENROLLMENT_RE = re.compile(
    r"(?i)\b("
    r"(?:manda|me\s+manda|envie|passa|quero)\s+(?:o\s+)?passo\s+a\s+passo"
    r"|passo\s+a\s+passo\s+da\s+matr[ií]cula"
    r"|como\s+(?:fa[cç]o|fazer)\s+a?\s*matr[ií]cula"
    r"|quero\s+(?:me\s+)?matricular"
    r"|quero\s+fazer\s+(?:a\s+)?matr[ií]cula"
    r"|vamos\s+(?:seguir|fechar|matricular)"
    r"|pode\s+seguir\s+com\s+a\s+matr[ií]cula"
    r"|já\s+decidi.*matr[ií]cula"
    r"|matricula\s+agora"
    r")"
)

_ASKS_OBJETIVO_RE = re.compile(
    r"(?i)\b("
    r"objetivo\s+(?:com|da|dessa|desta)\s+(?:p[oó]s|especializa)"
    r"|principal\s+objetivo"
    r"|[eé]\s+para\s+promo[cç][aã]o"
    r"|promo[cç][aã]o,\s*mudan[cç]a\s+de\s+[aá]rea"
    r"|crescer\s+na\s+sua\s+[aá]rea"
    r"|mudar\s+de\s+setor"
    r"|prestar\s+concurso"
    r"|atualiza[cç][aã]o\s+profissional"
    r")"
)

_REFUSES_QUESTION_RE = re.compile(
    r"(?i)\b("
    r"n[aã]o\s+quero\s+(?:falar|responder|essa|isso|perder\s+tempo|essa\s+confirma)"
    r"|n[aã]o\s+vou\s+(?:ficar\s+)?repetindo"
    r"|sem\s+(?:essa|isso|enrola)"
    r"|j[aá]\s+(?:falei|disse)"
    r"|n[aã]o\s+preciso\s+(?:disso|dessa)"
    r"|pula\s+(?:isso|essa)"
    r"|manda\s+logo"
    r"|sem\s+conversa\s+fiada"
    r")"
)


def reply_has_disallowed_price(text: str) -> bool:
    allowed = allowed_money_amounts()
    for m in _PRICE_RE.finditer(text or ""):
        if m.group(1).strip() not in allowed:
            return True
    return False


def lead_requests_enrollment(text: str) -> bool:
    return bool(_LEAD_ENROLLMENT_RE.search(text or ""))


def reply_offers_enrollment(text: str) -> bool:
    return bool(_OFFERS_ENROLLMENT_RE.search(text or ""))


def reply_asks_objetivo(text: str) -> bool:
    return bool(_ASKS_OBJETIVO_RE.search(text or ""))


def lead_refuses_question(text: str) -> bool:
    return bool(_REFUSES_QUESTION_RE.search(text or ""))


def claims_unbacked_action(
    reply: str,
    *,
    has_media: bool = False,
    just_entered_handoff: bool = False,
    handoff_avisado: bool = False,
    delivery_ran: bool = False,
) -> str | None:
    """Retorna submotivo se a reply afirma ação sem respaldo no código."""
    raw = reply or ""
    if _RECEIVED_DOC_RE.search(raw) and not has_media:
        return "recebeu_sem_midia"
    if _FAKE_CONFIRM_RE.search(raw):
        return "confirmacao_polo"
    if _HANDOFF_CLAIM_RE.search(raw):
        # Só a 1ª fala ao entrar em handoff neste turno é permitida.
        if handoff_avisado:
            return "handoff_repetido"
        if not just_entered_handoff:
            return "handoff_sem_acao"
    # “já preparei/enviei” sem delivery — coberto em parte por promessa_sem_acao;
    # reforço leve se afirmar passado sem delivery.
    if not delivery_ran and re.search(
        r"(?i)\b(j[aá]\s+(?:preparei|enviei|mandei)\s+(?:o\s+)?(?:contrato|pdf|link))\b",
        raw,
    ):
        return "entrega_afirmada"
    return None


def apply_enrollment_intent(ls: dict[str, Any], user_text: str) -> None:
    """Se o lead pede matrícula com curso definido, marca aceite_matricula."""
    if not lead_requests_enrollment(user_text):
        return
    if ls.get("curso_escolhido"):
        ls["aceite_matricula"] = True


def mark_refused_fields(meta: dict[str, Any], *, lead_text: str, last_agent: str) -> None:
    """Se o lead recusa após pergunta de objetivo, marca campo recusado."""
    if not lead_refuses_question(lead_text):
        return
    refused = list(meta.get("campos_recusados") or [])
    if reply_asks_objetivo(last_agent) and "objetivo" not in refused:
        refused.append("objetivo")
        meta["campos_recusados"] = refused
        ls = meta.get("lead_state") or {}
        ls["objetivo_recusado"] = True
        meta["lead_state"] = ls
