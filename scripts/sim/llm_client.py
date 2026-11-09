"""Chamadas OpenRouter com modelo explícito (lead/juiz)."""

from __future__ import annotations

import httpx

from app.config import Settings


async def chat(
    settings: Settings,
    messages: list[dict],
    *,
    model: str,
    temperature: float,
) -> str:
    if not settings.openrouter_api_key:
        raise RuntimeError("OPENROUTER_API_KEY não configurada")
    url = f"{settings.openrouter_base_url.rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {settings.openrouter_api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": settings.public_base_url or "https://localhost",
        "X-Title": "Edu SDR Sim",
    }
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
    }
    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(url, headers=headers, json=payload)
        if resp.status_code >= 400:
            raise RuntimeError(f"openrouter {resp.status_code}: {resp.text[:400]}")
        data = resp.json()
        return data["choices"][0]["message"]["content"].strip()
