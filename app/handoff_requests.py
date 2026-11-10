"""Pedidos de encaminhamento a especialista (Redis + fallback local). Idempotente."""

from __future__ import annotations

import json
import logging
import re
import time
import uuid
from typing import Any

import redis

from app.config import Settings, get_settings

logger = logging.getLogger("edu.handoff")

_REDIS_KEY = "edu:handoff_requests"
_local: dict[str, dict[str, Any]] = {}
_redis: redis.Redis | None | bool = False  # False = não inicializado


def _client(settings: Settings | None = None) -> redis.Redis | None:
    global _redis
    if _redis is False:
        s = settings or get_settings()
        if s.redis_url:
            try:
                r = redis.Redis.from_url(s.redis_url, decode_responses=True)
                r.ping()
                _redis = r
            except Exception as exc:  # noqa: BLE001
                logger.warning("Redis indisponível para handoffs: %s", exc)
                _redis = None
        else:
            _redis = None
    return _redis if _redis is not False else None


def _idempotency_key(phone: str, motivo: str) -> str:
    p = re.sub(r"\D", "", phone or "") or (phone or "unknown")
    m = re.sub(r"\s+", "_", (motivo or "geral").strip().casefold())[:80]
    return f"{p}:{m}"


def _load_all(settings: Settings | None = None) -> dict[str, dict[str, Any]]:
    r = _client(settings)
    if r:
        raw = r.hgetall(_REDIS_KEY) or {}
        out: dict[str, dict[str, Any]] = {}
        for k, v in raw.items():
            try:
                out[k] = json.loads(v)
            except json.JSONDecodeError:
                continue
        return out
    return dict(_local)


def _save_one(key: str, record: dict[str, Any], settings: Settings | None = None) -> None:
    r = _client(settings)
    payload = json.dumps(record, ensure_ascii=False)
    if r:
        r.hset(_REDIS_KEY, key, payload)
        return
    _local[key] = record


def register_handoff_request(
    *,
    phone: str,
    nome: str | None,
    motivo: str,
    curso: str | None,
    lead_summary: dict[str, Any] | None = None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Cria ou atualiza pedido (1 por telefone+motivo). Retorna o registro."""
    key = _idempotency_key(phone, motivo)
    now = time.time()
    existing = _load_all(settings).get(key)
    if existing:
        existing["updated_at"] = now
        existing["nome"] = nome or existing.get("nome")
        existing["curso"] = curso or existing.get("curso")
        if lead_summary:
            existing["lead_summary"] = lead_summary
        existing["status"] = existing.get("status") or "pending"
        _save_one(key, existing, settings)
        logger.info("handoff request updated key=%s motivo=%s", key, motivo)
        return existing

    record = {
        "id": str(uuid.uuid4()),
        "key": key,
        "phone": phone,
        "nome": nome,
        "motivo": motivo or "geral",
        "curso": curso,
        "lead_summary": lead_summary or {},
        "created_at": now,
        "updated_at": now,
        "status": "pending",
    }
    _save_one(key, record, settings)
    logger.info("handoff request created key=%s motivo=%s", key, motivo)
    return record


def list_handoff_requests(settings: Settings | None = None) -> list[dict[str, Any]]:
    items = list(_load_all(settings).values())
    items.sort(key=lambda x: float(x.get("updated_at") or 0), reverse=True)
    return items


def clear_handoff_requests(settings: Settings | None = None) -> int:
    """Só para testes/admin reset."""
    global _local
    r = _client(settings)
    n = 0
    if r:
        n = int(r.hlen(_REDIS_KEY) or 0)
        r.delete(_REDIS_KEY)
    n = max(n, len(_local))
    _local = {}
    return n


def lead_accepts_specialist(text: str) -> bool:
    return bool(
        re.search(
            r"(?i)\b("
            r"pode\s+(?:encaminhar|acionar|confirmar|verificar|chamar|anotar)"
            r"|pode\s+sim"
            r"|quero\s+(?:o\s+)?especialista"
            r"|fala\s+com\s+(?:o\s+)?especialista"
            r"|confirm(?:e|a|ar)\s+(?:mesmo\s+|direitinho\s+)?com\s+(?:o\s+)?(?:especialista|polo)"
            r"|sim,?\s+(?:pode|quero|confirme|por\s+favor)"
            r"|encaminhe(?:\s+para|\s+pro|\s+ao)?"
            r"|anota(?:\s+meu\s+caso)?"
            r"|me\s+avise\s+assim\s+que"
            r"|pede(?:\s+para|\s+pro)\s+(?:ele|o\s+especialista)"
            r"|passar?\s+(?:meu\s+)?(?:interesse|contato|pedido)"
            r")\b",
            text or "",
        )
    )


def lead_refuses_handoff(text: str) -> bool:
    """Recusa explícita de especialista/registro/encaminhamento."""
    return bool(
        re.search(
            r"(?i)\b("
            r"n[aã]o\s+quero\s+(?:especialista|registro|que\s+anotem|encaminh|"
            r"que\s+me\s+encaminh|intermedi[aá]rio)"
            r"|sem\s+intermedi[aá]rio"
            r"|n[aã]o\s+(?:quero\s+)?(?:anotar|encaminhar|registrar)"
            r"|n[aã]o\s+precisa\s+(?:registrar|encaminhar|anotar|especialista)"
            r"|deixa\s+pra\s+l[aá]"
            r")\b",
            text or "",
        )
    )


def agent_offered_specialist(text: str) -> bool:
    low = (text or "").casefold()
    return any(
        k in low
        for k in (
            "especialista",
            "encaminh",
            "anotar seu caso",
            "anoto seu caso",
            "passar seu interesse",
            "passar o contato",
            "registre seu pedido",
            "registrar seu pedido",
            "registrar o seu pedido",
        )
    )


def can_execute_register_handoff(
    *,
    last_assistant: str,
    user_text: str,
    already_registered: bool,
) -> tuple[bool, str]:
    """Gates da action REGISTER_HANDOFF."""
    if already_registered:
        return False, "ja_registrado"
    if not agent_offered_specialist(last_assistant):
        return False, "sem_oferta_previa"
    if lead_refuses_handoff(user_text):
        return False, "lead_recusou"
    if not lead_accepts_specialist(user_text):
        return False, "lead_nao_aceitou"
    return True, "ok"


def handoff_registered_reply(
    *,
    nome: str | None,
    motivo: str,
) -> str:
    first = (nome or "").strip().split()[0] if nome else ""
    raw = (motivo or "").strip()
    key = raw.replace("_", " ").casefold()
    # Slugs genéricos → fallback curto; frases reais (ex. vencimento) passam intactas.
    if key in ("", "especialista", "geral", "loop stock"):
        motivo_l = "sua dúvida"
    elif key in ("curso fora lista", "curso fora catalogo", "uti"):
        motivo_l = "essa especialização"
    elif key == "suporte aluno":
        motivo_l = "o suporte do polo"
    else:
        motivo_l = raw.replace("_", " ")
    if first:
        return (
            f"Registrei seu pedido, {first}. Um especialista do polo vai falar "
            f"com você por aqui sobre {motivo_l}."
        )
    return (
        f"Registrei seu pedido. Um especialista do polo vai falar com você "
        f"por aqui sobre {motivo_l}."
    )
