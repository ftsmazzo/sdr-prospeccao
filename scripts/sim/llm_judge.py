"""Fiscal de IA — notas 1–5 + veredito."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from app.config import Settings

from scripts.sim.llm_client import chat

logger = logging.getLogger("edu.sim.judge")

JUDGE_TEMPERATURE = 0.0

_SCORE_KEYS = ("escuta", "qualificacao", "objecao", "naturalidade", "conducao", "veracidade")


def _parse_judge_payload(raw: str) -> dict[str, Any] | None:
    try:
        m = re.search(r"\{[\s\S]*\}", raw)
        data = json.loads(m.group(0) if m else raw)
    except (json.JSONDecodeError, AttributeError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    for k in _SCORE_KEYS:
        if k not in data:
            return None
        try:
            data[k] = max(1, min(5, int(data.get(k, 1))))
        except (TypeError, ValueError):
            return None
    just = data.get("justificativas")
    if not isinstance(just, dict) or not just.get("veracidade"):
        return None
    if data.get("veredito") not in ("fechou", "proximo_passo", "perdeu", "encaminhou"):
        data["veredito"] = "proximo_passo"
    return data


def _erro_avaliacao(raw: str) -> dict[str, Any]:
    return {
        "escuta": None,
        "qualificacao": None,
        "objecao": None,
        "naturalidade": None,
        "conducao": None,
        "veracidade": None,
        "justificativas": {
            "erro": "erro_avaliacao",
            "veracidade": f"Falha de leitura do juiz após retry. bruto={raw[:300]!r}",
        },
        "veredito": "erro_avaliacao",
    }


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
  "veracidade": 1-5,
  "justificativas": {
    "escuta": "...",
    "qualificacao": "...",
    "objecao": "...",
    "naturalidade": "...",
    "conducao": "...",
    "veracidade": "..."
  },
  "veredito": "fechou"|"proximo_passo"|"perdeu"|"encaminhou"
}
Critérios: escuta=não reperguntar o já dito; qualificacao=graduação antes de matrícula (objetivo não bloqueia); objecao=acolheu+isolou+prova; naturalidade=soa humana; conducao=próximo passo concreto e ordem correta das etapas; veracidade=NÃO inventou fato, política, valor ou ação (ex.: recebi doc, confirmei com polo, preço inexistente, carga/duração errada).
IMPORTANTE — veracidade NÃO cobre problemas de processo/ordem (pedir CPF cedo, pular etapa, condução fraca). Isso vai em conducao (e/ou qualificacao), NÃO em veracidade. Se só houve falha de processo sem invenção, veracidade deve permanecer alta (4–5).
Se houver QUALQUER invenção de fato/política/valor/ação, veracidade <= 2 e isso deve pesar no veredito (prefira perdeu ou proximo_passo, não fechou).
veredito encaminhou = handoff/não elegível/aluno atual bem tratado."""
    user = (
        f"Persona: {persona.get('id')} — {persona.get('nome')}\n"
        f"Objetivo persona: {persona.get('objetivo')}\n"
        f"Objeção: {persona.get('objecao')}\n"
        f"Outcome técnico: {outcome_hint}\n"
        f"Violações automáticas: {json.dumps(violations, ensure_ascii=False)}\n\n"
        f"Conversa:\n{transcript}"
    )
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    raw = await chat(
        settings,
        messages,
        model=model,
        temperature=JUDGE_TEMPERATURE,
    )
    data = _parse_judge_payload(raw)
    if data is None:
        logger.warning("juiz JSON inválido — retry")
        raw2 = await chat(
            settings,
            messages
            + [
                {
                    "role": "system",
                    "content": (
                        "Sua resposta anterior não foi um JSON válido completo. "
                        "Responda APENAS o JSON com todas as notas 1-5, "
                        "justificativas (incluindo veracidade) e veredito."
                    ),
                }
            ],
            model=model,
            temperature=JUDGE_TEMPERATURE,
        )
        data = _parse_judge_payload(raw2)
        if data is None:
            return _erro_avaliacao(raw2 or raw)

    hard = {
        v.get("regra")
        for v in (violations or [])
        if isinstance(v, dict)
    }
    if hard & {"acao_fingida", "preco_fora_tabela"}:
        data["veracidade"] = min(int(data.get("veracidade") or 1), 2)
    return data
