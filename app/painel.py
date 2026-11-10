"""Agregações do painel do funil."""

from __future__ import annotations

import time
from typing import Any

from app.config import Settings
from app.memory import ConversationMemory

FUNNEL_COLUMNS = (
    "primeiro_contato",
    "abertura",
    "qualificacao",
    "recomendacao",
    "objecao",
    "fechamento",
    "contrato_enviado",
    "matriculado",
    "esfriou",
    "handoff_humano",
)


def _scan_lead_phones(settings: Settings) -> list[str]:
    """Lista phones com meta no Redis (melhor esforço)."""
    mem = ConversationMemory(settings)
    redis = getattr(mem, "_redis", None)
    if not redis:
        return []
    phones: list[str] = []
    try:
        # Chaves típicas: edu:meta:{phone}
        for key in redis.scan_iter(match="edu:meta:*", count=200):
            raw = key.decode() if isinstance(key, bytes) else str(key)
            phone = raw.split(":")[-1]
            if phone and phone not in phones:
                phones.append(phone)
    except Exception:  # noqa: BLE001
        return []
    return phones


def collect_painel(settings: Settings) -> dict[str, Any]:
    mem = ConversationMemory(settings)
    phones = _scan_lead_phones(settings)
    by_etapa: dict[str, list[dict[str, Any]]] = {e: [] for e in FUNNEL_COLUMNS}
    matriculas: list[dict[str, Any]] = []
    handoffs: list[dict[str, Any]] = []
    origem_counts: dict[str, int] = {}
    novos = 0
    negociacao = 0
    contratos = 0
    mats = 0
    now = time.time()
    day_ago = now - 86400

    for phone in phones:
        meta = mem.get_meta(phone)
        ls = meta.get("lead_state") or {}
        etapa = str(meta.get("etapa") or "abertura")
        if etapa not in by_etapa:
            by_etapa.setdefault(etapa, [])
        card = {
            "phone": phone,
            "nome": ls.get("nome") or meta.get("full_name") or phone,
            "origem": meta.get("origem") or "whatsapp",
            "curso": ls.get("curso_escolhido") or ls.get("curso_recomendado") or meta.get("interesse"),
            "etapa": etapa,
            "ultima_interacao": meta.get("ultima_interacao") or ls.get("ultima_interacao"),
            "proxima_retomada": meta.get("proxima_retomada_at"),
            "briefing": meta.get("briefing") or "",
            "opt_out": bool(meta.get("opt_out")),
            "retomadas_paused": bool(meta.get("retomadas_paused")),
        }
        by_etapa[etapa].append(card)
        origem = str(card["origem"])
        origem_counts[origem] = origem_counts.get(origem, 0) + 1
        created = float(meta.get("lead_created_at") or 0)
        if created >= day_ago:
            novos += 1
        if etapa in ("qualificacao", "recomendacao", "objecao", "fechamento", "abertura"):
            negociacao += 1
        if etapa == "contrato_enviado" or meta.get("contract_sent"):
            contratos += 1
        for m in meta.get("matriculas") or []:
            if isinstance(m, dict):
                mats += 1
                matriculas.append(
                    {
                        "phone": phone,
                        "curso": m.get("curso"),
                        "aluno_nome": m.get("aluno_nome"),
                        "comprador_nome": m.get("comprador_nome") or ls.get("nome"),
                        "at": m.get("at"),
                    }
                )
        if meta.get("handoff_registrado") or meta.get("handoff_request_id"):
            handoffs.append(
                {
                    "phone": phone,
                    "nome": card["nome"],
                    "motivo": meta.get("handoff_reason") or "especialista",
                    "etapa": etapa,
                    "briefing": card["briefing"],
                }
            )

    return {
        "ok": True,
        "indicadores": {
            "leads_novos": novos,
            "em_negociacao": negociacao,
            "contratos_enviados": contratos,
            "matriculas": mats,
            "conversao_por_origem": origem_counts,
        },
        "by_etapa": by_etapa,
        "matriculas": matriculas,
        "handoffs": handoffs,
        "phones_scanned": len(phones),
    }
