"""Inbox operacional — conversas + transferência humano/IA."""

from __future__ import annotations

import time
from typing import Any

from app.config import Settings
from app.lead_state import ensure_lead_state, enter_handoff
from app.memory import ConversationMemory
from app.painel import ETAPA_LABELS, _scan_lead_phones


def list_conversations(settings: Settings) -> list[dict[str, Any]]:
    mem = ConversationMemory(settings)
    out: list[dict[str, Any]] = []
    for phone in _scan_lead_phones(settings):
        meta = mem.get_meta(phone)
        ls = meta.get("lead_state") if isinstance(meta.get("lead_state"), dict) else {}
        hist = mem.get_history(phone)
        last = hist[-1] if hist else None
        preview = ""
        if isinstance(last, dict):
            preview = str(last.get("content") or "")[:120]
        etapa = str(meta.get("etapa") or "abertura")
        out.append(
            {
                "phone": phone,
                "nome": ls.get("nome") or meta.get("full_name") or phone,
                "etapa": etapa,
                "etapa_label": ETAPA_LABELS.get(etapa, etapa),
                "ai_paused": bool(meta.get("ai_paused")),
                "modo": "humano" if meta.get("ai_paused") else "ia",
                "origem": meta.get("origem") or "whatsapp",
                "curso": ls.get("curso_escolhido")
                or ls.get("curso_recomendado")
                or meta.get("interesse"),
                "messages_count": len(hist),
                "preview": preview,
                "updated_at": meta.get("inbox_updated_at")
                or ls.get("ultima_interacao")
                or meta.get("ultima_interacao"),
            }
        )
    out.sort(key=lambda c: str(c.get("updated_at") or ""), reverse=True)
    return out


def get_conversation(settings: Settings, phone: str) -> dict[str, Any] | None:
    digits = "".join(ch for ch in phone if ch.isdigit())
    if not digits:
        return None
    mem = ConversationMemory(settings)
    meta = mem.get_meta(digits)
    if not meta and not mem.get_history(digits):
        return None
    ls = ensure_lead_state(meta)
    hist = mem.get_history(digits)
    messages = []
    for m in hist:
        if not isinstance(m, dict):
            continue
        role = str(m.get("role") or "assistant")
        source = str(m.get("source") or "")
        if source == "human" or role == "operator":
            bucket = "human"
        elif role == "user":
            bucket = "lead"
        else:
            bucket = "ai"
        messages.append(
            {
                "role": role,
                "bucket": bucket,
                "content": str(m.get("content") or ""),
                "source": source or None,
            }
        )
    etapa = str(meta.get("etapa") or "abertura")
    return {
        "phone": digits,
        "nome": ls.get("nome") or meta.get("full_name") or digits,
        "etapa": etapa,
        "etapa_label": ETAPA_LABELS.get(etapa, etapa),
        "ai_paused": bool(meta.get("ai_paused")),
        "modo": "humano" if meta.get("ai_paused") else "ia",
        "origem": meta.get("origem") or "whatsapp",
        "curso": ls.get("curso_escolhido")
        or ls.get("curso_recomendado")
        or meta.get("interesse"),
        "handoff_reason": meta.get("handoff_reason"),
        "messages": messages,
        "meta_flags": {
            "retomadas_paused": bool(meta.get("retomadas_paused")),
            "opt_out": bool(meta.get("opt_out")),
            "contract_sent": bool(meta.get("contract_sent")),
        },
    }


def transfer_to_human(settings: Settings, phone: str, *, reason: str = "inbox_operador") -> dict[str, Any]:
    from app.followups import get_scheduler
    from app.outbound_cadence import cancel_retomadas

    digits = "".join(ch for ch in phone if ch.isdigit())
    mem = ConversationMemory(settings)
    meta = mem.get_meta(digits)
    ensure_lead_state(meta)
    if not meta.get("ai_paused"):
        meta["etapa_antes_ai_pause"] = meta.get("etapa") or "objecao"
    meta["ai_paused"] = True
    meta["retomadas_paused"] = True
    meta["inbox_updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    enter_handoff(meta, reason)
    cancel_retomadas(digits, get_scheduler())
    meta["proxima_retomada_at"] = None
    mem.set_meta(digits, meta)
    return {"ok": True, "phone": digits, "modo": "humano", "etapa": meta.get("etapa")}


def return_to_ai(settings: Settings, phone: str) -> dict[str, Any]:
    from app.followups import get_scheduler
    from app.outbound_cadence import cancel_retomadas

    digits = "".join(ch for ch in phone if ch.isdigit())
    mem = ConversationMemory(settings)
    meta = mem.get_meta(digits)
    ensure_lead_state(meta)
    prev = meta.get("etapa_antes_ai_pause") or meta.get("etapa_antes_handoff") or "objecao"
    if prev in ("handoff_humano", "esfriou", "matriculado"):
        prev = "objecao"
    meta["ai_paused"] = False
    meta["retomadas_paused"] = False
    meta["etapa"] = prev
    meta.pop("handoff_reason", None)
    meta["inbox_updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    cancel_retomadas(digits, get_scheduler())
    meta["proxima_retomada_at"] = None
    mem.set_meta(digits, meta)
    return {"ok": True, "phone": digits, "modo": "ia", "etapa": meta.get("etapa")}


async def send_operator_message(
    settings: Settings, phone: str, text: str
) -> dict[str, Any]:
    """Envia WhatsApp como operador e registra no histórico."""
    from app.clients.evolution import EvolutionClient

    digits = "".join(ch for ch in phone if ch.isdigit())
    body = (text or "").strip()
    if not digits or not body:
        return {"ok": False, "error": "mensagem_vazia"}
    mem = ConversationMemory(settings)
    meta = mem.get_meta(digits)
    ensure_lead_state(meta)
    # Operador respondendo ⇒ IA fica pausada.
    if not meta.get("ai_paused"):
        transfer_to_human(settings, digits, reason="inbox_operador_envio")
        meta = mem.get_meta(digits)
    evo = EvolutionClient(settings)
    await evo.send_text(digits, body, delay_ms=0)
    mem.append(digits, "assistant", body, source="human")
    meta["inbox_updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    mem.set_meta(digits, meta)
    return {"ok": True, "phone": digits, "modo": "humano"}
