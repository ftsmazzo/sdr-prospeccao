import logging

import httpx

from app.config import Settings

logger = logging.getLogger("edu.evolution")


class EvolutionClient:
    def __init__(self, settings: Settings):
        self.base = settings.evolution_base_url.rstrip("/")
        self.api_key = settings.evolution_api_key
        self.instance = settings.evolution_instance

    def _headers(self) -> dict[str, str]:
        return {"apikey": self.api_key, "Content-Type": "application/json"}

    async def send_text(self, phone: str, text: str) -> dict:
        number = phone.split("@")[0].replace("+", "")
        url = f"{self.base}/message/sendText/{self.instance}"
        payload = {
            "number": number,
            "text": text,
            "delay": 1200,
            "linkPreview": False,
        }
        async with httpx.AsyncClient(timeout=45.0) as client:
            resp = await client.post(url, headers=self._headers(), json=payload)
            if resp.status_code >= 400:
                logger.error("sendText failed %s %s", resp.status_code, resp.text[:500])
                resp.raise_for_status()
            return resp.json()
