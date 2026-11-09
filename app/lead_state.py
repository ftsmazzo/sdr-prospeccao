"""Estado do lead e máquina de etapas (decisão só no código)."""

from __future__ import annotations

import logging
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

# Campos que o modelo pode atualizar via state_update
STATE_WHITELIST = {
    "nome",
    "graduacao",
    "area_interesse",
    "objetivo",
    "restricao",
    "decisor",
    "objecoes_levantadas",
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

# Nunca aceitos do modelo
STATE_FORBIDDEN = {
    "etapa",
    "pending_contract",
    "contract_sent",
    "full_name",
    "cpf",
    "birth_date",
    "objecoes_sem_avanco",
}


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _as_bool(value: Any) -> bool:
    """Parse estrito: só True real ou strings true/1/sim/yes."""
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


def default_lead_state() -> dict[str, Any]:
    return {
        "nome": None,
        "graduacao": None,
        "area_interesse": None,
        "objetivo": None,
        "restricao": None,
        "decisor": None,
        "objecoes_levantadas": [],
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
    """Garante lead_state + migra meta antigo. Retorna o dict lead_state."""
    if "objecoes_sem_avanco" not in meta:
        meta["objecoes_sem_avanco"] = 0

    if isinstance(meta.get("lead_state"), dict) and meta.get("etapa"):
        ls = {**default_lead_state(), **meta["lead_state"]}
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
    for key, value in update.items():
        if key in STATE_FORBIDDEN or key == "etapa":
            logger.warning("state_update ignorou campo proibido: %s", key)
            continue
        if key not in STATE_WHITELIST:
            continue
        if key == "objecoes_levantadas":
            existing = list(ls.get("objecoes_levantadas") or [])
            if isinstance(value, list):
                for item in value:
                    s = str(item).strip()
                    if s and s not in existing:
                        existing.append(s)
            elif value:
                s = str(value).strip()
                if s and s not in existing:
                    existing.append(s)
            ls["objecoes_levantadas"] = existing
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
        if key in ("aceite_matricula", "e_aluno_atual", "lead_irritado", "pediu_desconto_ou_condicao", "duvida_juridica"):
            ls[key] = _as_bool(value)
            continue
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        ls[key] = value.strip() if isinstance(value, str) else value
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
        f"objecoes={ls.get('objecoes_levantadas')}",
        f"pending_contract={meta.get('pending_contract')}",
    ]
    return "; ".join(parts)


def advance_etapa(meta: dict[str, Any], *, handoff_max_objecoes: int = 3) -> str:
    """Decide a próxima etapa. Mutates meta['etapa']."""
    ls = meta["lead_state"]
    etapa = meta.get("etapa") or "abertura"
    prev = etapa

    # Handoff imediato
    if ls.get("pediu_desconto_ou_condicao") or ls.get("duvida_juridica") or ls.get("lead_irritado"):
        meta["etapa"] = "handoff_humano"
        logger.info("handoff_humano trigger imediato phone_meta summary=%s", summarize_lead(meta))
        return meta["etapa"]

    # Aluno atual só com flag explícita
    if ls.get("e_aluno_atual"):
        meta["etapa"] = "aluno_atual"
        return meta["etapa"]

    # Graduação
    grad = ls.get("graduacao")
    if grad == "nao_tem":
        meta["etapa"] = "nao_elegivel"
        return meta["etapa"]

    # Contrato já enviado
    if meta.get("contract_sent"):
        meta["etapa"] = "contrato_enviado"
        return meta["etapa"]

    # Contagem de objeções sem avanço (antes de decidir handoff)
    objecoes = list(ls.get("objecoes_levantadas") or [])
    prev_count = int(meta.get("_objecoes_count_seen", 0) or 0)
    new_objecoes = max(0, len(objecoes) - prev_count)
    if new_objecoes and prev in ("objecao", "fechamento", "recomendacao"):
        meta["objecoes_sem_avanco"] = int(meta.get("objecoes_sem_avanco") or 0) + new_objecoes
    if len(objecoes) != prev_count:
        meta["_objecoes_count_seen"] = len(objecoes)

    if int(meta.get("objecoes_sem_avanco") or 0) >= handoff_max_objecoes:
        meta["etapa"] = "handoff_humano"
        logger.info("handoff_humano por objecoes_sem_avanco=%s", meta.get("objecoes_sem_avanco"))
        return meta["etapa"]

    # Transição para trás: nova objeção em fechamento
    if (
        prev == "fechamento"
        and new_objecoes
        and len(objecoes) > int(meta.get("_objecoes_at_fechamento", 0) or 0)
    ):
        meta["_etapa_antes_objecao"] = "fechamento"
        meta["etapa"] = "objecao"
        meta["_objecoes_at_fechamento"] = len(objecoes)
        return meta["etapa"]

    # Fluxo principal
    if prev in ("abertura",):
        meta["etapa"] = "qualificacao"
        etapa = "qualificacao"

    if etapa in ("qualificacao", "abertura"):
        if grad == "cursando":
            meta["etapa"] = "qualificacao"
            return meta["etapa"]
        if grad == "concluida" and ls.get("area_interesse") and ls.get("objetivo"):
            meta["etapa"] = "recomendacao"
            meta["objecoes_sem_avanco"] = 0
            etapa = "recomendacao"
        else:
            meta["etapa"] = "qualificacao"
            return meta["etapa"]

    if etapa == "nao_elegivel":
        if grad == "concluida":
            meta["etapa"] = "qualificacao"
            return advance_etapa(meta, handoff_max_objecoes=handoff_max_objecoes)
        return "nao_elegivel"

    if etapa == "recomendacao":
        if ls.get("curso_escolhido") and ls.get("aceite_matricula"):
            meta["etapa"] = "fechamento"
            meta["objecoes_sem_avanco"] = 0
            meta["_objecoes_at_fechamento"] = len(objecoes)
            return meta["etapa"]
        if objecoes:
            meta["etapa"] = "objecao"
            meta["_etapa_antes_objecao"] = "recomendacao"
            return meta["etapa"]
        meta["etapa"] = "recomendacao"
        return "recomendacao"

    if etapa == "objecao":
        if ls.get("curso_escolhido") and ls.get("aceite_matricula"):
            meta["etapa"] = "fechamento"
            meta["objecoes_sem_avanco"] = 0
            return meta["etapa"]
        if not objecoes and not ls.get("curso_escolhido"):
            meta["etapa"] = "recomendacao"
            return meta["etapa"]
        meta["etapa"] = "objecao"
        return "objecao"

    if etapa == "fechamento":
        meta["etapa"] = "fechamento"
        return "fechamento"

    if etapa == "contrato_enviado":
        meta["etapa"] = "contrato_enviado"
        return "contrato_enviado"

    if etapa in ("aluno_atual", "handoff_humano", "matriculado"):
        meta["etapa"] = etapa
        return etapa

    meta["etapa"] = etapa
    return meta["etapa"]


def can_run_action(meta: dict[str, Any], action: str | None) -> tuple[bool, str]:
    if not action:
        return True, "no_action"
    etapa = meta.get("etapa")
    ls = meta.get("lead_state") or {}

    if action in ("LEAD_DATA", "FOLLOWUP_DOC"):
        if etapa != "fechamento":
            return False, f"action={action} bloqueada etapa={etapa}"
        if not ls.get("curso_escolhido") or not ls.get("aceite_matricula"):
            return False, f"action={action} exige curso_escolhido+aceite"
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
            return False, "CHECKOUT_READY sem curso_escolhido"
        if not ls.get("aceite_matricula"):
            return False, "CHECKOUT_READY exige aceite_matricula"
        return True, "ok"

    return False, f"action desconhecida {action}"


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
    return meta
