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

# Futuro / andamento inventado (nunca ok, mesmo com registro).
_FAKE_SPECIALIST_PROGRESS_RE = re.compile(
    r"(?i)\b("
    r"vou\s+refor[cç]ar"
    r"|vou\s+(?:verificar|confirmar|acionar|consultar)\s+(?:com\s+)?"
    r"(?:o\s+)?(?:especialista|polo|equipe)"
    r"|te\s+aviso\s+quando"
    r"|assim\s+que\s+(?:tiver|receber)\s+(?:a\s+)?(?:resposta|confirma[cç][aã]o|retorno)"
    r"|ainda\s+n[aã]o\s+(?:recebi|tenho)\s+(?:o\s+)?(?:retorno|confirma[cç][aã]o)"
    r"|estou\s+aguardando\s+(?:o\s+)?especialista"
    r"|aguardando\s+(?:o\s+)?(?:retorno|confirma[cç][aã]o)\s+(?:do\s+)?especialista"
    r"|encaminhei"
    r"|j[aá]\s+encaminhei"
    r"|vou\s+encaminhar"
    r"|pedi\s+pra\s+(?:um\s+)?especialista"
    r")"
)

# “Assim que o documento chegar” — só se o lead disse que vai enviar.
_DOC_ARRIVAL_PROMISE_RE = re.compile(
    r"(?i)\bassim\s+que\s+(?:o\s+|a\s+|seu\s+|sua\s+)?"
    r"(?:documento|rg|cnh|foto|arquivo|pdf|diploma)\s+"
    r"(?:chegar|chegar\s+por\s+aqui|for\s+enviado)"
)

# “Registrei” — só no turno em que o código gravou.
_CLAIMS_JUST_REGISTERED_RE = re.compile(
    r"(?i)\bregistrei\s+(?:seu|o)\s+pedido\b"
)

# Status após registro (ok se handoff_registrado, qualquer turno).
_HANDOFF_STATUS_RE = re.compile(
    r"(?i)\b("
    r"pedido\s+est[aá]\s+registrado"
    r"|especialista\s+(?:do\s+polo\s+)?(?:vai|vai\s+te)\s+"
    r"(?:falar|ajudar|retomar|entrar|dar\s+sequ[eê]ncia|te\s+chama)"
    r"|especialista\s+te\s+chama"
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

# Lead pede matrícula / passo a passo / contrato.
_LEAD_ENROLLMENT_RE = re.compile(
    r"(?i)\b("
    r"(?:manda|me\s+manda|envie|passa|quero)\s+(?:o\s+)?passo\s+a\s+passo"
    r"|passo\s+a\s+passo\s+(?:para\s+)?(?:da\s+)?matr[ií]cula"
    r"|passos\s+para\s+matr[ií]cula"
    r"|como\s+(?:fa[cç]o|fazer)\s+a?\s*matr[ií]cula"
    r"|quero\s+(?:me\s+)?matricular"
    r"|quero\s+fazer\s+(?:a\s+)?matr[ií]cula"
    r"|quero\s+fechar(?:\s+hoje)?"
    r"|vamos\s+(?:seguir|fechar|matricular)"
    r"|pode\s+seguir\s+com\s+a\s+matr[ií]cula"
    r"|já\s+decidi.*matr[ií]cula"
    r"|matr[ií]cula\s+agora"
    r"|encaminha(?:r)?\s+(?:o\s+)?contrato"
    r"|(?:manda|envie|envia|quero)\s+(?:o\s+)?contrato"
    r"|pode\s+encaminhar\s+contrato"
    r")"
)

# CPF no texto do lead (11 dígitos com ou sem máscara).
_LEAD_CPF_IN_TEXT_RE = re.compile(
    r"(?i)(?:\bcpf\b\s*[:.]?\s*)?(\d{3}\.?\d{3}\.?\d{3}-?\d{2})\b"
)

_LEAD_SENDING_DOC_RE = re.compile(
    r"(?i)\b("
    r"(?:vou|posso|j[aá]\s+vou)\s+(?:te\s+)?(?:enviar|mandar|passar)\s+"
    r"(?:o\s+|meu\s+|a\s+|minha\s+)?(?:rg|cnh|cpf|diploma|documento|foto|arquivo|hist)"
    r"|mando\s+(?:o\s+|meu\s+)?(?:rg|documento|foto)"
    r"|segue\s+(?:o\s+)?(?:rg|documento|foto)"
    r"|enviei\s+(?:o\s+)?(?:rg|documento|foto)"
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


def lead_says_sending_document(text: str) -> bool:
    return bool(_LEAD_SENDING_DOC_RE.search(text or ""))


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
    handoff_registered_this_turn: bool = False,
    handoff_registrado: bool = False,
    lead_sending_document: bool = False,
) -> str | None:
    """Retorna submotivo se a reply afirma ação sem respaldo no código."""
    raw = reply or ""
    if _RECEIVED_DOC_RE.search(raw) and not has_media:
        return "recebeu_sem_midia"
    if _DOC_ARRIVAL_PROMISE_RE.search(raw) and not lead_sending_document:
        return "documento_sem_envio"
    if _FAKE_CONFIRM_RE.search(raw):
        return "confirmacao_polo"
    # Verificar/aguardar especialista: sempre fingido (registro ≠ consulta).
    if _FAKE_SPECIALIST_PROGRESS_RE.search(raw):
        return "especialista_sem_acao"
    if _CLAIMS_JUST_REGISTERED_RE.search(raw):
        if not handoff_registered_this_turn:
            return "registro_sem_acao"
    elif _HANDOFF_STATUS_RE.search(raw):
        if not (handoff_registrado or handoff_registered_this_turn):
            return "registro_sem_acao"
        if handoff_avisado and not handoff_registered_this_turn:
            # status curto ok; evitar spam de "especialista vai" em loop
            if re.search(r"(?i)\bregistrei\b", raw):
                return "handoff_repetido"
    # “já preparei/enviei” sem delivery — coberto em parte por promessa_sem_acao;
    # reforço leve se afirmar passado sem delivery.
    if not delivery_ran and re.search(
        r"(?i)\b(j[aá]\s+(?:preparei|enviei|mandei)\s+(?:o\s+)?(?:contrato|pdf|link))\b",
        raw,
    ):
        return "entrega_afirmada"
    _ = just_entered_handoff  # reservado / compat
    return None


def reply_has_markdown_list(text: str) -> bool:
    """True se há marcadores de lista típicos de Markdown (ruim no WhatsApp)."""
    return bool(
        re.search(r"(?m)^(?:\s*[-*•]\s+|\s*\d+[.)]\s+)", text or "")
        or re.search(r"\n\s*[-*•]\s+\S", text or "")
    )


def lead_sends_cpf(text: str) -> bool:
    m = _LEAD_CPF_IN_TEXT_RE.search(text or "")
    if not m:
        return False
    digits = re.sub(r"\D", "", m.group(1))
    return len(digits) == 11


def apply_enrollment_intent(ls: dict[str, Any], user_text: str) -> None:
    """Aceite se pede matrícula/contrato ou manda CPF, com curso + graduação ok."""
    if not ls.get("curso_escolhido"):
        return
    grad = ls.get("graduacao")
    if grad in ("cursando", "nao_tem"):
        return
    wants = lead_requests_enrollment(user_text) or lead_sends_cpf(user_text)
    if wants and grad == "concluida":
        ls["aceite_matricula"] = True
    elif wants and grad is None and lead_sends_cpf(user_text):
        # CPF + curso: trata como aceite; graduação ainda pode ser pedida no fluxo.
        ls["aceite_matricula"] = True
    elif lead_requests_enrollment(user_text):
        # Pedido explícito de matrícula com curso (graduação pode já estar ok ou null).
        if grad != "cursando" and grad != "nao_tem":
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
