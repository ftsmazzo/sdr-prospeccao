"""Fiscal de IA — notas 1–5 + veredito."""

from __future__ import annotations

import json
import re
from typing import Any

from app.config import Settings

from scripts.sim.llm_client import chat

JUDGE_TEMPERATURE = 0.0


async def judge_conversation(
    settings: Settings,
    *,
    model: str,
    persona: dict[str, Any],
    history: list[dict[str, str]],
    violations: list[dict[str, Any]],
    outcome_hint: str,
) -> dict[str, Any]:
    transcript = "\n".join(
        f"{'LEAD' if h['role'] == 'lead' else 'AGENTE'}: {h['text']}" for h in history
    )
    system = """Você avalia uma conversa de SDR de matrícula (pós EAD) no WhatsApp.
Responda APENAS JSON válido:
{
  "escuta": 1-5,
  "qualificacao": 1-5,
  "objecao": 1-5,
  "naturalidade": 1-5,
  "conducao": 1-5,
  "justificativas": {
    "escuta": "...",
    "qualificacao": "...",
    "objecao": "...",
    "naturalidade": "...",
    "conducao": "..."
  },
  "veredito": "fechou"|"proximo_passo"|"perdeu"|"encaminhou"
}
Critérios: escuta=não reperguntar o já dito; qualificacao=graduação/área/objetivo antes de recomendar; objecao=acolheu+isolou+prova; naturalidade=soa humana; conducao=próximo passo concreto.
veredito encaminhou = handoff/não elegível/aluno atual bem tratado."""
    user = (
        f"Persona: {persona.get('id')} — {persona.get('nome')}\n"
        f"Objetivo persona: {persona.get('objetivo')}\n"
        f"Objeção: {persona.get('objecao')}\n"
        f"Outcome técnico: {outcome_hint}\n"
        f"Violações automáticas: {json.dumps(violations, ensure_ascii=False)}\n\n"
        f"Conversa:\n{transcript}"
    )
    raw = await chat(
        settings,
        [{"role": "system", "content": system}, {"role": "user", "content": user}],
        model=model,
        temperature=JUDGE_TEMPERATURE,
    )
    try:
        m = re.search(r"\{[\s\S]*\}", raw)
        data = json.loads(m.group(0) if m else raw)
    except (json.JSONDecodeError, AttributeError):
        data = {
            "escuta": 1,
            "qualificacao": 1,
            "objecao": 1,
            "naturalidade": 1,
            "conducao": 1,
            "justificativas": {"erro": raw[:300]},
            "veredito": "perdeu",
        }
    for k in ("escuta", "qualificacao", "objecao", "naturalidade", "conducao"):
        try:
            data[k] = max(1, min(5, int(data.get(k, 1))))
        except (TypeError, ValueError):
            data[k] = 1
    if data.get("veredito") not in ("fechou", "proximo_passo", "perdeu", "encaminhou"):
        data["veredito"] = "proximo_passo"
    return data
