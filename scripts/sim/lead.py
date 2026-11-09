"""Lead simulado via LLM."""

from __future__ import annotations

import json
import re
from typing import Any

from app.config import Settings

from scripts.sim.llm_client import chat

LEAD_TEMPERATURE = 0.85


def build_lead_system(persona: dict[str, Any]) -> str:
    return f"""Você é {persona.get('nome', 'um lead')} conversando no WhatsApp com uma consultora de matrícula da Faveni.

Perfil: {persona.get('perfil', '')}
Objetivo: {persona.get('objetivo', '')}
Objeção principal: {persona.get('objecao', '')}
Estilo de escrita: {persona.get('estilo', 'mensagens curtas e naturais')}
Quando fechar: {persona.get('fecha_quando', 'quando se sentir seguro')}
Quando desistir: {persona.get('desiste_quando', 'se insistirem demais ou inventarem coisa')}

Regras:
- Você NUNCA sabe que isso é um teste. Não ajude a consultora.
- Responda como lead real de WhatsApp (pt-BR).
- Não invente que já matriculou se não combinou.
- Se o estilo for mensagens picadas, você vai receber instrução para gerar 2–3 pedaços curtos.
- Se quiser desistir, diga claramente (ex.: "deixa pra lá", "não quero mais").
- Se for enviar dados (nome/CPF/nascimento), use dados fictícios críveis.
"""


async def generate_lead_message(
    settings: Settings,
    *,
    model: str,
    persona: dict[str, Any],
    history: list[dict[str, str]],
    picado: bool,
) -> str | list[str]:
    system = build_lead_system(persona)
    if picado:
        system += (
            "\nAgora responda com JSON: {\"messages\": [\"msg1\", \"msg2\"]} "
            "com 2 ou 3 mensagens CURTAS (estilo WhatsApp picado). Só o JSON."
        )
    else:
        system += "\nResponda só com o texto da sua próxima mensagem no WhatsApp (sem aspas, sem JSON)."

    messages: list[dict] = [{"role": "system", "content": system}]
    transcript = []
    for h in history[-16:]:
        who = "Consultora" if h["role"] == "agent" else "Lead"
        transcript.append(f"{who}: {h['text']}")
    messages.append(
        {
            "role": "user",
            "content": "Histórico:\n"
            + ("\n".join(transcript) if transcript else "(início da conversa)")
            + "\n\nSua próxima resposta como lead:",
        }
    )

    raw = await chat(settings, messages, model=model, temperature=LEAD_TEMPERATURE)
    if picado:
        try:
            # extract JSON
            m = re.search(r"\{[\s\S]*\}", raw)
            data = json.loads(m.group(0) if m else raw)
            msgs = [str(x).strip() for x in data.get("messages", []) if str(x).strip()]
            if len(msgs) >= 2:
                return msgs[:3]
        except (json.JSONDecodeError, AttributeError, TypeError):
            pass
        parts = [p.strip() for p in re.split(r"\n+", raw) if p.strip()]
        if len(parts) >= 2:
            return parts[:3]
        return [raw.strip()]
    return raw.strip()
