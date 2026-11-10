"""Estado do lead e máquina de etapas (decisão só no código)."""

from __future__ import annotations

import logging
import re
import unicodedata
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger("edu.lead_state")

ETAPAS = (
    "abertura",
    "qualificacao",
    "recomendacao",
    "objecao",
    "fechamento",
    "contrato_enviado",
    "matriculado",
    "nao_elegivel",
    "aluno_atual",
    "handoff_humano",
)

GRADUACAO = ("concluida", "cursando", "nao_tem")

OBJECAO_CATEGORIAS = (
    "preco",
    "tempo",
    "validade_ead",
    "qualidade",
    "vou_pensar",
    "conjuge",
    "ja_tentei",
    "outro",
)

STATE_WHITELIST = {
    "nome",
    "graduacao",
    "area_interesse",
    "objetivo",
    "objetivo_recusado",
    "restricao",
    "decisor",
    "objecoes_levantadas",
    "objecao_ativa",
    "perguntou_desconto",
    "curso_recomendado",
    "curso_escolhido",
    "curso_alternativo",
    "aceite_matricula",
    "e_aluno_atual",
    "lead_irritado",
    "pediu_desconto_ou_condicao",
    "duvida_juridica",
    "proximo_passo",
}

STATE_FORBIDDEN = {
    "etapa",
    "pending_contract",
    "contract_sent",
    "full_name",
    "cpf",
    "birth_date",
    "objecoes_sem_avanco",
    "desconto_respondido",
    "handoff_reason",
    "etapa_antes_handoff",
}

# Promessa = agente diz que VAI ENTREGAR algo (verbo 1ª pessoa + objeto).
# Palavra solta (matrícula, contrato, documento, link) NÃO é promessa.
_PROMISE_DELIVERY_RES: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"\b(?:ja\s+)?vou(?:\s+ja)?\s+"
        r"(?:te\s+)?"
        r"(?:preparar|gerar|mandar|enviar|separar)\b"
        r".{0,80}?"
        r"\b(?:contrato|pdf|informativo|link|sua\s+matricula)\b",
        re.IGNORECASE | re.DOTALL,
    ),
    re.compile(
        r"\b(?:preparei|gerei|separei|montei)\b"
        r".{0,80}?"
        r"\b(?:contrato|pdf|informativo|link|sua\s+matricula)\b",
        re.IGNORECASE | re.DOTALL,
    ),
    re.compile(
        r"\b(?:ja\s+)?(?:te\s+)?(?:mando|envio|mandei|enviei)\b"
        r".{0,60}?"
        r"\b(?:contrato|pdf|informativo|link|sua\s+matricula)\b",
        re.IGNORECASE | re.DOTALL,
    ),
    re.compile(
        r"\b(?:segue|aqui\s+esta|aqui\s+vai|segue\s+em\s+anexo)\b"
        r".{0,60}?"
        r"\b(?:o\s+)?(?:link|contrato|pdf|informativo)\b",
        re.IGNORECASE | re.DOTALL,
    ),
    re.compile(
        r"\b(?:em\s+alguns\s+minutos|em\s+instantes|daqui\s+a\s+pouco|"
        r"em\s+alguns\s+minutinhos)\b"
        r".{0,80}?"
        r"\b(?:contrato|pdf|link|informativo|sua\s+matricula)\b",
        re.IGNORECASE | re.DOTALL,
    ),
)

# Lembrete / retorno futuro — ainda sem follow-up automático (Fase 4).
_PROMISE_CALLBACK_RES: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"\b(?:vou|posso)\s+(?:te\s+)?chamar\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bte\s+chamo\s+(?:daqui|em|depois|logo)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:vou|posso)\s+(?:te\s+)?(?:enviar|mandar)\s+(?:um\s+)?lembrete\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\blembrete\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:vou|posso)\s+(?:te\s+)?avisar\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bte\s+aviso\s+se\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:vou\s+)?lembrar\s+de\s+te\s+(?:chamar|enviar|avisar)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bacompanhar\s+(?:sua|a)\s+decis(?:ao|ão)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bvoltar\s+a\s+(?:te\s+)?chamar\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:daqui|em)\s+(?:a\s+)?(?:alguns|uns)\s+dias\b"
        r".{0,40}?"
        r"\b(?:chamar|lembrete|avisar|acompanhar)\b",
        re.IGNORECASE | re.DOTALL,
    ),
)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        v = value.strip().lower()
        if v in ("true", "1", "sim", "yes", "s"):
            return True
        if v in ("false", "0", "nao", "não", "no", "n", ""):
            return False
    return False


def _norm_categoria(value: Any) -> str | None:
    if value is None:
        return None
    v = str(value).strip().lower()
    if not v or v in ("null", "none"):
        return None
    if v in OBJECAO_CATEGORIAS:
        return v
    return None


def default_lead_state() -> dict[str, Any]:
    return {
        "nome": None,
        "graduacao": None,
        "area_interesse": None,
        "objetivo": None,
        "objetivo_recusado": False,
        "restricao": None,
        "decisor": None,
        "objecoes_levantadas": [],
        "objecao_ativa": None,
        "perguntou_desconto": False,
        "curso_recomendado": None,
        "curso_escolhido": None,
        "curso_alternativo": None,
        "aceite_matricula": False,
        "e_aluno_atual": False,
        "lead_irritado": False,
        "pediu_desconto_ou_condicao": False,
        "duvida_juridica": False,
        "proximo_passo": None,
        "ultima_interacao": None,
    }


def ensure_lead_state(meta: dict[str, Any]) -> dict[str, Any]:
    if "objecoes_sem_avanco" not in meta:
        meta["objecoes_sem_avanco"] = 0
    if "desconto_respondido" not in meta:
        meta["desconto_respondido"] = False

    if isinstance(meta.get("lead_state"), dict) and meta.get("etapa"):
        ls = {**default_lead_state(), **meta["lead_state"]}
        cats: list[str] = []
        for item in ls.get("objecoes_levantadas") or []:
            c = _norm_categoria(item)
            if c and c not in cats:
                cats.append(c)
        ls["objecoes_levantadas"] = cats
        ls["objecao_ativa"] = _norm_categoria(ls.get("objecao_ativa"))
        # flags de turno — não ficam sticky no Redis entre mensagens
        ls["perguntou_desconto"] = False
        ls["pediu_desconto_ou_condicao"] = False
        ls["duvida_juridica"] = False
        ls["lead_irritado"] = False
        meta["lead_state"] = ls
        return ls

    ls = default_lead_state()
    if meta.get("full_name"):
        ls["nome"] = meta["full_name"]
    if meta.get("course"):
        ls["curso_escolhido"] = meta["course"]

    if meta.get("contract_sent"):
        etapa = "contrato_enviado"
    elif meta.get("pending_contract"):
        etapa = "fechamento"
        if meta.get("course"):
            ls["aceite_matricula"] = True
    elif meta.get("full_name") or meta.get("course"):
        etapa = "fechamento" if meta.get("full_name") else "recomendacao"
    else:
        etapa = "abertura"

    meta["lead_state"] = ls
    meta["etapa"] = etapa
    return ls


def merge_state_update(ls: dict[str, Any], update: dict[str, Any] | None) -> dict[str, Any]:
    if not update:
        return ls
    prev_ativa = ls.get("objecao_ativa")
    for key, value in update.items():
        if key in STATE_FORBIDDEN or key == "etapa":
            logger.warning("state_update ignorou campo proibido: %s", key)
            continue
        if key not in STATE_WHITELIST:
            continue
        if key == "objecoes_levantadas":
            existing = list(ls.get("objecoes_levantadas") or [])
            items = value if isinstance(value, list) else ([value] if value else [])
            for item in items:
                c = _norm_categoria(item)
                if c and c not in existing:
                    existing.append(c)
            ls["objecoes_levantadas"] = existing
            continue
        if key == "objecao_ativa":
            if value is None or (
                isinstance(value, str) and value.strip().lower() in ("", "null", "none")
            ):
                ls["objecao_ativa"] = None
            else:
                ls["objecao_ativa"] = _norm_categoria(value)
            continue
        if key == "perguntou_desconto":
            ls["perguntou_desconto"] = _as_bool(value)
            continue
        if key == "graduacao" and value is not None:
            v = str(value).strip().lower()
            if v in GRADUACAO:
                ls["graduacao"] = v
            continue
        if key == "restricao" and value is not None:
            v = str(value).strip().lower()
            if v in ("tempo", "preco", "outro"):
                ls["restricao"] = v
            continue
        if key in (
            "aceite_matricula",
            "e_aluno_atual",
            "lead_irritado",
            "pediu_desconto_ou_condicao",
            "duvida_juridica",
            "objetivo_recusado",
        ):
            ls[key] = _as_bool(value)
            continue
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        ls[key] = value.strip() if isinstance(value, str) else value
    ls["_prev_objecao_ativa"] = prev_ativa
    ls["ultima_interacao"] = _now_iso()
    return ls


def summarize_lead(meta: dict[str, Any]) -> str:
    ls = meta.get("lead_state") or {}
    parts = [
        f"etapa={meta.get('etapa')}",
        f"nome={ls.get('nome')}",
        f"graduacao={ls.get('graduacao')}",
        f"area={ls.get('area_interesse')}",
        f"objetivo={ls.get('objetivo')}",
        f"curso_escolhido={ls.get('curso_escolhido')}",
        f"aceite={ls.get('aceite_matricula')}",
        f"objecao_ativa={ls.get('objecao_ativa')}",
        f"objecoes={ls.get('objecoes_levantadas')}",
        f"desconto_respondido={meta.get('desconto_respondido')}",
        f"handoff_reason={meta.get('handoff_reason')}",
        f"pending_contract={meta.get('pending_contract')}",
    ]
    return "; ".join(parts)


def enter_handoff(meta: dict[str, Any], reason: str) -> str:
    """Entra em handoff_humano com motivo (público para orquestrador/sim)."""
    if meta.get("etapa") != "handoff_humano":
        meta["etapa_antes_handoff"] = meta.get("etapa") or "recomendacao"
    meta["handoff_reason"] = reason
    meta["etapa"] = "handoff_humano"
    logger.info("handoff_humano reason=%s summary=%s", reason, summarize_lead(meta))
    return "handoff_humano"


def _enter_handoff(meta: dict[str, Any], reason: str) -> str:
    return enter_handoff(meta, reason)


def _clear_handoff_flags(ls: dict[str, Any], meta: dict[str, Any]) -> None:
    ls["pediu_desconto_ou_condicao"] = False
    ls["duvida_juridica"] = False
    ls["lead_irritado"] = False
    meta["objecoes_sem_avanco"] = 0
    meta.pop("handoff_reason", None)


def _ensure_preco_objection(ls: dict[str, Any]) -> None:
    hist = list(ls.get("objecoes_levantadas") or [])
    if "preco" not in hist:
        hist.append("preco")
        ls["objecoes_levantadas"] = hist
    if not ls.get("objecao_ativa"):
        ls["objecao_ativa"] = "preco"


def _curso_no_catalogo(curso: str) -> bool:
    if not (curso or "").strip():
        return False
    try:
        from app.pricing import lookup_course_hours

        return lookup_course_hours(curso) is not None
    except Exception:
        return False


def advance_etapa(meta: dict[str, Any], *, handoff_max_objecoes: int = 3) -> str:
    ls = meta["lead_state"]
    etapa = meta.get("etapa") or "abertura"
    prev = etapa
    prev_ativa = ls.pop("_prev_objecao_ativa", ls.get("objecao_ativa"))

    # Flags de turno (como perguntou_desconto): avaliar e zerar
    perguntou = bool(ls.get("perguntou_desconto"))
    pediu_condicao = bool(ls.get("pediu_desconto_ou_condicao"))
    duvida_juridica = bool(ls.get("duvida_juridica"))
    lead_irritado = bool(ls.get("lead_irritado"))
    ls["perguntou_desconto"] = False
    ls["pediu_desconto_ou_condicao"] = False
    ls["duvida_juridica"] = False
    ls["lead_irritado"] = False

    mark_desconto_respondido = False
    if perguntou:
        if meta.get("desconto_respondido"):
            return _enter_handoff(meta, "desconto_insistencia")
        _ensure_preco_objection(ls)
        mark_desconto_respondido = True

    # Já em handoff: etapa mantém; flags novas reforçam, sem mexer em etapa_antes_handoff
    if prev == "handoff_humano":
        if pediu_condicao or duvida_juridica or lead_irritado:
            if pediu_condicao:
                meta["handoff_reason"] = "condicao_especial"
            elif duvida_juridica:
                meta["handoff_reason"] = "duvida_juridica"
            else:
                meta["handoff_reason"] = "lead_irritado"
            meta["etapa"] = "handoff_humano"
            if mark_desconto_respondido:
                meta["desconto_respondido"] = True
            return "handoff_humano"
        if ls.get("curso_escolhido") and ls.get("aceite_matricula") and not ls.get("objecao_ativa"):
            _clear_handoff_flags(ls, meta)
            meta["etapa"] = "fechamento"
            if mark_desconto_respondido:
                meta["desconto_respondido"] = True
            return "fechamento"
        meta["etapa"] = "handoff_humano"
        if mark_desconto_respondido:
            meta["desconto_respondido"] = True
        return "handoff_humano"

    # Entrada em handoff a partir de outras etapas
    if pediu_condicao:
        if mark_desconto_respondido:
            meta["desconto_respondido"] = True
        return _enter_handoff(meta, "condicao_especial")
    if duvida_juridica:
        if mark_desconto_respondido:
            meta["desconto_respondido"] = True
        return _enter_handoff(meta, "duvida_juridica")
    if lead_irritado:
        if mark_desconto_respondido:
            meta["desconto_respondido"] = True
        return _enter_handoff(meta, "lead_irritado")

    if ls.get("e_aluno_atual"):
        meta["etapa"] = "aluno_atual"
        if mark_desconto_respondido:
            meta["desconto_respondido"] = True
        return meta["etapa"]

    grad = ls.get("graduacao")
    if grad == "nao_tem":
        meta["etapa"] = "nao_elegivel"
        if mark_desconto_respondido:
            meta["desconto_respondido"] = True
        return meta["etapa"]

    if meta.get("contract_sent"):
        meta["etapa"] = "contrato_enviado"
        if mark_desconto_respondido:
            meta["desconto_respondido"] = True
        return meta["etapa"]

    hist = list(ls.get("objecoes_levantadas") or [])
    seen = set(meta.get("_objecoes_cats_seen") or [])
    new_cats = [c for c in hist if c not in seen]
    ativa = ls.get("objecao_ativa")
    reopened = bool(ativa and prev_ativa is None and ativa in seen)

    bumped = 0
    if prev in ("objecao", "fechamento", "recomendacao"):
        bumped += len(new_cats)
        if reopened and ativa not in new_cats:
            bumped += 1
    if bumped:
        meta["objecoes_sem_avanco"] = int(meta.get("objecoes_sem_avanco") or 0) + bumped
    if hist:
        meta["_objecoes_cats_seen"] = sorted(set(seen) | set(hist))

    if int(meta.get("objecoes_sem_avanco") or 0) >= handoff_max_objecoes:
        if mark_desconto_respondido:
            meta["desconto_respondido"] = True
        return _enter_handoff(meta, "objecoes_sem_avanco")

    if prev in ("abertura",):
        meta["etapa"] = "qualificacao"
        etapa = "qualificacao"

    if etapa in ("qualificacao", "abertura"):
        if grad == "cursando":
            meta["etapa"] = "qualificacao"
            if mark_desconto_respondido:
                meta["desconto_respondido"] = True
            return meta["etapa"]
        # Atalho: lead decidido (graduação + curso do catálogo + aceite) → fechamento.
        # objetivo NUNCA bloqueia matrícula.
        if (
            grad == "concluida"
            and ls.get("curso_escolhido")
            and ls.get("aceite_matricula")
            and not ls.get("objecao_ativa")
            and _curso_no_catalogo(str(ls.get("curso_escolhido") or ""))
        ):
            meta["etapa"] = "fechamento"
            meta["objecoes_sem_avanco"] = 0
            if mark_desconto_respondido:
                meta["desconto_respondido"] = True
            return "fechamento"
        objetivo_ok = bool(ls.get("objetivo")) or bool(ls.get("objetivo_recusado"))
        if grad == "concluida" and ls.get("area_interesse") and objetivo_ok:
            meta["etapa"] = "recomendacao"
            meta["objecoes_sem_avanco"] = 0
            etapa = "recomendacao"
        elif grad == "concluida" and ls.get("curso_escolhido") and objetivo_ok:
            # Curso já escolhido + objetivo ok (ou recusado) → recomendacao sem área.
            meta["etapa"] = "recomendacao"
            meta["objecoes_sem_avanco"] = 0
            etapa = "recomendacao"
        else:
            meta["etapa"] = "qualificacao"
            if mark_desconto_respondido:
                meta["desconto_respondido"] = True
            return meta["etapa"]

    if etapa == "nao_elegivel":
        if grad == "concluida":
            meta["etapa"] = "qualificacao"
            return advance_etapa(meta, handoff_max_objecoes=handoff_max_objecoes)
        if mark_desconto_respondido:
            meta["desconto_respondido"] = True
        return "nao_elegivel"

    if etapa == "recomendacao":
        if ativa:
            meta["_etapa_antes_objecao"] = "recomendacao"
            meta["etapa"] = "objecao"
            if mark_desconto_respondido:
                meta["desconto_respondido"] = True
            return "objecao"
        if ls.get("curso_escolhido") and ls.get("aceite_matricula"):
            meta["etapa"] = "fechamento"
            meta["objecoes_sem_avanco"] = 0
            if mark_desconto_respondido:
                meta["desconto_respondido"] = True
            return "fechamento"
        meta["etapa"] = "recomendacao"
        if mark_desconto_respondido:
            meta["desconto_respondido"] = True
        return "recomendacao"

    if etapa == "fechamento":
        if ativa:
            meta["_etapa_antes_objecao"] = "fechamento"
            ls["aceite_matricula"] = False
            meta["etapa"] = "objecao"
            if mark_desconto_respondido:
                meta["desconto_respondido"] = True
            return "objecao"
        meta["etapa"] = "fechamento"
        if mark_desconto_respondido:
            meta["desconto_respondido"] = True
        return "fechamento"

    if etapa == "objecao":
        if not ativa and ls.get("curso_escolhido") and ls.get("aceite_matricula"):
            meta["etapa"] = "fechamento"
            meta["objecoes_sem_avanco"] = 0
            if mark_desconto_respondido:
                meta["desconto_respondido"] = True
            return "fechamento"
        if not ativa:
            back = meta.get("_etapa_antes_objecao") or "recomendacao"
            if back == "fechamento" and not ls.get("aceite_matricula"):
                back = "recomendacao"
            if back not in ("recomendacao", "fechamento"):
                back = "recomendacao"
            meta["etapa"] = back
            if mark_desconto_respondido:
                meta["desconto_respondido"] = True
            return back
        meta["etapa"] = "objecao"
        if mark_desconto_respondido:
            meta["desconto_respondido"] = True
        return "objecao"

    if etapa == "contrato_enviado":
        meta["etapa"] = "contrato_enviado"
        if mark_desconto_respondido:
            meta["desconto_respondido"] = True
        return "contrato_enviado"

    if etapa in ("aluno_atual", "matriculado"):
        meta["etapa"] = etapa
        if mark_desconto_respondido:
            meta["desconto_respondido"] = True
        return etapa

    meta["etapa"] = etapa
    if mark_desconto_respondido:
        meta["desconto_respondido"] = True
    return meta["etapa"]


def can_run_action(meta: dict[str, Any], action: str | None) -> tuple[bool, str]:
    if not action:
        return True, "no_action"
    etapa = meta.get("etapa")
    ls = meta.get("lead_state") or {}

    if action in ("LEAD_DATA", "FOLLOWUP_DOC"):
        if etapa != "fechamento":
            return False, f"action={action} bloqueada etapa={etapa}"
        if not ls.get("curso_escolhido"):
            return False, f"action={action} sem_curso"
        if not ls.get("aceite_matricula"):
            return False, f"action={action} sem_aceite"
        if ls.get("graduacao") in ("cursando", "nao_tem"):
            return False, f"action={action} bloqueada graduacao={ls.get('graduacao')}"
        if action == "FOLLOWUP_DOC" and meta.get("pending_contract"):
            return False, "FOLLOWUP_DOC bloqueada pending_contract"
        if action == "FOLLOWUP_DOC" and meta.get("contract_sent"):
            return False, "FOLLOWUP_DOC bloqueada contract_sent"
        return True, "ok"

    if action == "CHECKOUT_READY":
        if meta.get("pending_contract"):
            return False, "CHECKOUT_READY bloqueado pending_contract"
        if etapa not in ("fechamento", "contrato_enviado"):
            return False, f"CHECKOUT_READY bloqueada etapa={etapa}"
        if not ls.get("curso_escolhido"):
            return False, "CHECKOUT_READY sem_curso"
        if not ls.get("aceite_matricula"):
            return False, "CHECKOUT_READY sem_aceite"
        return True, "ok"

    if action == "REGISTER_HANDOFF":
        # Gates finos (oferta prévia / aceite / recusa) ficam no orquestrador.
        if meta.get("handoff_registrado"):
            return False, "REGISTER_HANDOFF ja_registrado"
        return True, "ok"

    return False, f"action desconhecida {action}"


def _fold_accents(text: str) -> str:
    norm = unicodedata.normalize("NFD", text or "")
    return "".join(ch for ch in norm if unicodedata.category(ch) != "Mn")


def reply_looks_like_delivery_promise(reply: str) -> bool:
    """True se promete ENTREGAR contrato/PDF/link (não só mencionar o assunto)."""
    folded = _fold_accents(reply or "")
    return any(rx.search(folded) for rx in _PROMISE_DELIVERY_RES)


def reply_looks_like_callback_promise(reply: str) -> bool:
    """True se promete lembrete, retorno ou 'te chamo depois' (sem follow-up automático)."""
    folded = _fold_accents(reply or "")
    return any(rx.search(folded) for rx in _PROMISE_CALLBACK_RES)


def reply_looks_like_promise(reply: str) -> bool:
    """True se promete entrega de documento/link OU lembrete/retorno futuro."""
    return reply_looks_like_delivery_promise(reply) or reply_looks_like_callback_promise(
        reply
    )


def _stock_variants(reason: str, ls: dict[str, Any]) -> list[str]:
    """Frases prontas residuais (só após 2ª regeneração falhar)."""
    if "pending_contract" in reason:
        return [
            (
                "Seu contrato já está sendo preparado. Em alguns minutinhos eu te mando "
                "o informativo por aqui."
            ),
            (
                "O informativo já está a caminho — assim que sair eu te mando por aqui. "
                "Enquanto isso, tem alguma dúvida sobre o curso?"
            ),
        ]
    if "contract_sent" in reason:
        return [
            (
                "O contrato já foi enviado. Se estiver tudo certo, me avisa que seguimos "
                "com a confirmação da matrícula."
            ),
            (
                "Você já recebeu o contrato por aqui. Conseguiu abrir? Se estiver ok, "
                "seguimos com a confirmação."
            ),
        ]

    if reason == "promessa_lembrete":
        return [
            "Quando quiser retomar, é só me chamar aqui.",
            "Combinado. Quando quiser retomar, é só me chamar por aqui.",
            "Sem problema — quando quiser retomar, é só me chamar aqui.",
        ]

    curso = ls.get("curso_escolhido") or "esse curso"
    if "sem_curso" in reason:
        return [
            "Antes de eu preparar o contrato, me confirma qual curso você quer seguir?",
            "Qual especialização você quer seguir? Assim eu te passo as informações certas.",
            "Me confirma o nome do curso que você escolheu pra eu te orientar no próximo passo?",
        ]
    if "sem_aceite" in reason:
        return [
            (
                f"Perfeito — só pra eu seguir certo: você confirma que quer matricular "
                f"em {curso} agora?"
            ),
            (
                f"Você quer seguir com a matrícula em {curso}, ou ainda prefere "
                "só tirar dúvidas?"
            ),
        ]

    if reason in ("fato_curso_errado", "preco_fora_tabela"):
        try:
            from app.course_facts import stock_reply_from_facts

            built = stock_reply_from_facts(ls)
            if built:
                return [built]
        except Exception:  # noqa: BLE001
            pass
        if reason == "fato_curso_errado":
            curso_f = ls.get("curso_escolhido") or ls.get("curso_recomendado") or "essa pós"
            return [
                (
                    f"Sobre {curso_f}: te passo carga, prazo e valores certinhos. "
                    "Quer que eu detalhe mensalidade e à vista?"
                ),
            ]
        return [
            (
                "A mensalidade é a da faixa do seu curso; à vista é o valor total "
                "com 10%. Quer que eu te diga os três números (mensal, 18x e à vista)?"
            ),
        ]

    if reason == "matricula_sem_graduacao":
        return [
            (
                "Antes de falar do passo a passo da matrícula, preciso saber: "
                "sua graduação já está concluída?"
            ),
            (
                "Pra eu te orientar certo na matrícula: você já concluiu a graduação?"
            ),
        ]

    # Residual genérico: só despedida segura (2ª regen deveria ter respondido).
    return [
        "Quando quiser retomar, é só me chamar aqui.",
    ]


def rewrite_blocked_action_reply(
    reason: str,
    reply: str,
    ls: dict[str, Any],
    *,
    avoid: str | None = None,
) -> str:
    """Fallback stock após regeneração falhar. Nunca repete o texto em `avoid`."""
    _ = reply
    variants = _stock_variants(reason, ls)
    avoid_norm = (avoid or "").strip()
    for text in variants:
        if text.strip() != avoid_norm:
            return text
    return variants[-1] if variants else (
        "Me conta o que você precisa saber agora que eu te respondo por aqui."
    )


def reset_etapa(meta: dict[str, Any], etapa: str = "qualificacao") -> dict[str, Any]:
    ensure_lead_state(meta)
    if etapa not in ETAPAS:
        etapa = "qualificacao"
    meta["etapa"] = etapa
    ls = meta["lead_state"]
    if etapa in ("abertura", "qualificacao", "recomendacao"):
        ls["aceite_matricula"] = False
    meta["objecoes_sem_avanco"] = 0
    ls["lead_irritado"] = False
    ls["pediu_desconto_ou_condicao"] = False
    ls["duvida_juridica"] = False
    ls["e_aluno_atual"] = False
    ls["objecao_ativa"] = None
    ls["perguntou_desconto"] = False
    meta.pop("handoff_reason", None)
    return meta
