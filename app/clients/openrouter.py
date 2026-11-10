import logging
from typing import Any

import httpx

from app.config import Settings

logger = logging.getLogger("edu.openrouter")


def _message_text(message: dict[str, Any] | None) -> str:
    """Extrai texto útil de message OpenRouter (Claude pode devolver content null)."""
    if not isinstance(message, dict):
        return ""
    content = message.get("content")
    if isinstance(content, str) and content.strip():
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str) and block.strip():
                parts.append(block.strip())
            elif isinstance(block, dict):
                txt = block.get("text") or block.get("content")
                if isinstance(txt, str) and txt.strip():
                    parts.append(txt.strip())
        if parts:
            return "\n".join(parts).strip()
    # Fallback: alguns modelos reasoning colocam o útil em reasoning/refusal
    for key in ("reasoning", "refusal"):
        alt = message.get(key)
        if isinstance(alt, str) and alt.strip():
            return alt.strip()
    return ""


class OpenRouterClient:
    def __init__(self, settings: Settings):
        self.base = settings.openrouter_base_url.rstrip("/")
        self.api_key = settings.openrouter_api_key
        self.model = settings.openrouter_model

    async def chat(self, messages: list[dict], temperature: float = 0.6) -> str:
        if not self.api_key:
            raise RuntimeError("OPENROUTER_API_KEY não configurada")

        url = f"{self.base}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://sdr-prospeccao-api.kxryyk.easypanel.host",
            "X-Title": "Edu SDR",
        }
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
        }
        # Sonnet 5: reasoning alto pode esvaziar content; force effort baixo + JSON.
        if "claude-sonnet-5" in (self.model or "").casefold():
            payload["reasoning"] = {"effort": "low"}
            # Ajuda a não devolver prose/fences no caminho do agente.
            wants_json = any(
                "json" in str(m.get("content") or "").casefold()
                for m in messages
                if isinstance(m, dict)
            )
            if wants_json:
                payload["response_format"] = {"type": "json_object"}
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(url, headers=headers, json=payload)
            if resp.status_code >= 400:
                logger.error("openrouter failed %s %s", resp.status_code, resp.text[:500])
                resp.raise_for_status()
            data = resp.json()
            choices = data.get("choices") or []
            if not choices:
                logger.error("openrouter sem choices: %s", str(data)[:500])
                return ""
            msg = choices[0].get("message") or {}
            text = _message_text(msg)
            if not text:
                logger.error(
                    "openrouter content vazio model=%s finish=%s msg_keys=%s",
                    self.model,
                    choices[0].get("finish_reason"),
                    list(msg.keys()),
                )
            return text
