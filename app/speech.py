"""Preparo de texto para TTS — preserva calor humano, evita locução de vídeo."""

from __future__ import annotations

import re

import httpx

from app.clients.openrouter import OpenRouterClient

SPOKEN_REWRITE_SYSTEM = """Você adapta a mensagem do Edu para ÁUDIO de WhatsApp (pt-BR).

Objetivo: a pessoa deve SENTIR a mesma empatia e calor do texto original — só que falado.

Regras:
- Mantenha o tom caloroso e humano. Não deixe seco, frio ou “atendimento robô”.
- Pode ter até 3 frases curtas. Se houver pergunta, no máximo UMA no final.
- Preserve acolhimento concreto (“entendo sua preocupação”, “faz sentido”, “fica tranquilo”).
- Corte só o que não funciona em áudio: links, listas longas, markdown, emojis, marcadores técnicos.
- Não invente informação nova. Não vire locutora institucional.
- Não comece com “Olá” se o original não começa assim.
- Saída: apenas o texto a ser falado.
"""


def scrub_for_tts(text: str) -> str:
    t = text
    t = re.sub(r"https?://\S+", "", t)
    t = re.sub(r"CHECKOUT_READY\|.*", "", t)
    t = re.sub(r"FOLLOWUP_DOC\|.*", "", t)
    t = t.replace("—", ",").replace("–", ",")
    t = t.replace("...", ".")
    t = re.sub(r"[*_`#>]+\s*", "", t)
    t = re.sub(r"\s*\n+\s*", ". ", t)
    t = re.sub(r"\s{2,}", " ", t)
    t = re.sub(r"([!?.]){2,}", r"\1", t)
    return t.strip(" .,;")


async def to_spoken_script(llm: OpenRouterClient, written: str) -> str:
    """Gera versão falada mantendo empatia; se falhar, usa scrub curto."""
    cleaned = scrub_for_tts(written)
    if len(cleaned) < 8:
        return cleaned
    try:
        spoken = await llm.chat(
            [
                {"role": "system", "content": SPOKEN_REWRITE_SYSTEM},
                {
                    "role": "user",
                    "content": (
                        "Reescreva para áudio preservando o calor desta mensagem:\n\n"
                        + cleaned[:900]
                    ),
                },
            ],
            temperature=0.55,
        )
        spoken = scrub_for_tts(spoken)
        # áudio um pouco mais longo ok — prioridade é soar humano
        if len(spoken) > 420:
            spoken = spoken[:420].rsplit(" ", 1)[0]
        return spoken or cleaned
    except (httpx.HTTPError, RuntimeError, KeyError, IndexError):
        parts = re.split(r"(?<=[.!?])\s+", cleaned)
        short = " ".join(parts[:3]).strip()
        return short[:420] or cleaned
