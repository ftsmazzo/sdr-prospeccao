import logging

import httpx

from app.config import Settings

logger = logging.getLogger("edu.openrouter")


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
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
        }
        async with httpx.AsyncClient(timeout=90.0) as client:
            resp = await client.post(url, headers=headers, json=payload)
            if resp.status_code >= 400:
                logger.error("openrouter failed %s %s", resp.status_code, resp.text[:500])
                resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"].strip()
