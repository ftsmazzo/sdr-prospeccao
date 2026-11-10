import logging
from typing import Any

import httpx

from app.config import Settings

logger = logging.getLogger("edu.openrouter")


def _is_sonnet5(model: str) -> bool:
    return "claude-sonnet-5" in (model or "").casefold()


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
    for key in ("reasoning", "refusal"):
        alt = message.get(key)
        if isinstance(alt, str) and alt.strip():
            return alt.strip()
    return ""


def _tool_call_arguments(message: dict[str, Any] | None) -> str | None:
    if not isinstance(message, dict):
        return None
    tool_calls = message.get("tool_calls")
    if not isinstance(tool_calls, list) or not tool_calls:
        return None
    first = tool_calls[0]
    if not isinstance(first, dict):
        return None
    fn = first.get("function") or {}
    if not isinstance(fn, dict):
        return None
    args = fn.get("arguments")
    if isinstance(args, str) and args.strip():
        return args.strip()
    if isinstance(args, dict):
        import json

        return json.dumps(args, ensure_ascii=False)
    return None


def _log_cache_usage(usage: dict[str, Any] | None, *, model: str) -> None:
    if not isinstance(usage, dict):
        return
    prompt = int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0)
    # OpenRouter / Anthropic: cache_read_input_tokens ou prompt_tokens_details
    cached = int(
        usage.get("cache_read_input_tokens")
        or usage.get("cached_tokens")
        or 0
    )
    details = usage.get("prompt_tokens_details") or usage.get("input_tokens_details")
    if isinstance(details, dict) and not cached:
        cached = int(details.get("cached_tokens") or details.get("cache_read_tokens") or 0)
    pct = (100.0 * cached / prompt) if prompt > 0 else 0.0
    logger.info(
        "openrouter usage model=%s prompt=%s cached=%s cache_pct=%.1f completion=%s",
        model,
        prompt,
        cached,
        pct,
        usage.get("completion_tokens") or usage.get("output_tokens"),
    )


class OpenRouterClient:
    def __init__(self, settings: Settings):
        self.base = settings.openrouter_base_url.rstrip("/")
        self.api_key = settings.openrouter_api_key
        self.model = settings.openrouter_model
        self.last_usage: dict[str, Any] = {}

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://sdr-prospeccao-api.kxryyk.easypanel.host",
            "X-Title": "Edu SDR",
        }

    async def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.api_key:
            raise RuntimeError("OPENROUTER_API_KEY não configurada")
        url = f"{self.base}/chat/completions"
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(url, headers=self._headers(), json=payload)
            if resp.status_code >= 400:
                logger.error("openrouter failed %s %s", resp.status_code, resp.text[:500])
                resp.raise_for_status()
            return resp.json()

    def _base_payload(self, messages: list[dict], *, temperature: float | None) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
        }
        if _is_sonnet5(self.model):
            payload["reasoning"] = {"effort": "low"}
            # Sonnet 5 ignora temperature — não enviar.
        elif temperature is not None:
            payload["temperature"] = temperature
        return payload

    async def chat(self, messages: list[dict], temperature: float | None = 0.6) -> str:
        """Chat livre (TTS rewrite etc.). Sem tool calling."""
        payload = self._base_payload(messages, temperature=temperature)
        data = await self._post(payload)
        usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
        self.last_usage = dict(usage or {})
        _log_cache_usage(self.last_usage, model=self.model)
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

    async def chat_tool(
        self,
        messages: list[dict],
        *,
        tools: list[dict[str, Any]],
        tool_choice: dict[str, Any] | str,
        temperature: float | None = 0.4,
    ) -> str:
        """Força tool call; retorna arguments JSON (ou content como reserva)."""
        payload = self._base_payload(messages, temperature=temperature)
        payload["tools"] = tools
        payload["tool_choice"] = tool_choice
        data = await self._post(payload)
        usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
        self.last_usage = dict(usage or {})
        _log_cache_usage(self.last_usage, model=self.model)
        choices = data.get("choices") or []
        if not choices:
            logger.error("openrouter tool sem choices: %s", str(data)[:500])
            return ""
        msg = choices[0].get("message") or {}
        args = _tool_call_arguments(msg)
        if args:
            return args
        # Reserva: content textual
        text = _message_text(msg)
        if not text:
            logger.error(
                "openrouter tool sem arguments model=%s finish=%s msg_keys=%s",
                self.model,
                choices[0].get("finish_reason"),
                list(msg.keys()),
            )
        return text
