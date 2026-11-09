"""Preparo de texto para TTS — evita fala 'vídeo de IA'."""

from __future__ import annotations

import re

import httpx

from app.clients.openrouter import OpenRouterClient

SPOKEN_REWRITE_SYSTEM = """Você reescreve mensagens para ÁUDIO de WhatsApp em português do Brasil.

Regras obrigatórias:
- Soa como pessoa real no zap, NÃO como locutora de vídeo/institucional.
- No máximo 2 frases curtas. Se precisar de pergunta, só UMA no final.
- Empatia leve e seca (ex.: "entendi"), sem drama ("é uma escolha muito importante...").
- Evite listas, travessões, reticências longas, emojis e formalidade.
- Não invente informação. Não inclua links.
- Saída: só o texto falado, nada mais.
"""


def scrub_for_tts(text: str) -> str:
    t = text
    t = re.sub(r"https?://\S+", "", t)
    t = re.sub(r"CHECKOUT_READY\|.*", "", t)
    t = t.replace("—", ",").replace("–", ",")
    t = t.replace("...", ".")
    t = re.sub(r"[*_`#>]+\s*", "", t)
    t = re.sub(r"\s*\n+\s*", ". ", t)
    t = re.sub(r"\s{2,}", " ", t)
    t = re.sub(r"([!?.]){2,}", r"\1", t)
    return t.strip(" .,;")


async def to_spoken_script(llm: OpenRouterClient, written: str) -> str:
    """Gera versão falada; se falhar, usa scrub simples."""
    cleaned = scrub_for_tts(written)
    if len(cleaned) < 8:
        return cleaned
    try:
        spoken = await llm.chat(
            [
                {"role": "system", "content": SPOKEN_REWRITE_SYSTEM},
                {"role": "user", "content": cleaned[:700]},
            ],
            temperature=0.4,
        )
        spoken = scrub_for_tts(spoken)
        # hard cap: áudio longo vira cadência de vídeo
        if len(spoken) > 280:
            spoken = spoken[:280].rsplit(" ", 1)[0]
        return spoken or cleaned
    except (httpx.HTTPError, RuntimeError, KeyError, IndexError):
        # fallback local
        parts = re.split(r"(?<=[.!?])\s+", cleaned)
        short = " ".join(parts[:2]).strip()
        return short[:280] or cleaned
