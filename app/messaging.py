"""Utilitários de timing e quebra de mensagem no estilo WhatsApp humano."""

from __future__ import annotations

import re


def split_whatsapp_messages(text: str, *, soft_limit: int = 240, hard_limit: int = 360) -> list[str]:
    """Quebra resposta longa em no máximo 2 bolhas, em fronteira natural."""
    cleaned = (text or "").strip()
    if not cleaned:
        return []
    if len(cleaned) <= soft_limit:
        return [cleaned]

    # Preferir quebra por parágrafo / linha em branco
    parts = [p.strip() for p in re.split(r"\n\s*\n", cleaned) if p.strip()]
    if len(parts) >= 2:
        first, rest = parts[0], "\n\n".join(parts[1:])
        if len(first) <= hard_limit and len(rest) <= hard_limit * 1.5:
            return [first, rest]

    # Quebra por frase perto do soft_limit
    sentences = re.split(r"(?<=[.!?…])\s+", cleaned)
    if len(sentences) >= 2:
        buf = ""
        cut = 0
        for i, s in enumerate(sentences):
            candidate = (buf + " " + s).strip() if buf else s
            if len(candidate) <= soft_limit or (i == 0 and len(s) <= hard_limit):
                buf = candidate
                cut = i + 1
            else:
                break
        if cut and cut < len(sentences):
            first = " ".join(sentences[:cut]).strip()
            second = " ".join(sentences[cut:]).strip()
            if first and second:
                return [first, second]

    # Fallback: metade em espaço
    mid = len(cleaned) // 2
    space = cleaned.rfind(" ", 0, mid + 40)
    if space < soft_limit // 2:
        space = cleaned.find(" ", mid)
    if space > 0:
        return [cleaned[:space].strip(), cleaned[space:].strip()]
    return [cleaned]
