import base64
import logging
from typing import Any

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

    @staticmethod
    def _number(phone: str) -> str:
        return phone.split("@")[0].replace("+", "")

    async def send_presence(self, phone: str, delay_ms: int = 4000) -> None:
        """Mostra 'digitando...' no WhatsApp."""
        url = f"{self.base}/chat/sendPresence/{self.instance}"
        payload = {
            "number": self._number(phone),
            "presence": "composing",
            "delay": delay_ms,
        }
        async with httpx.AsyncClient(timeout=45.0) as client:
            resp = await client.post(url, headers=self._headers(), json=payload)
            if resp.status_code >= 400:
                logger.warning("sendPresence failed %s %s", resp.status_code, resp.text[:300])

    async def send_text(self, phone: str, text: str, delay_ms: int = 3500) -> dict:
        url = f"{self.base}/message/sendText/{self.instance}"
        payload = {
            "number": self._number(phone),
            "text": text,
            "delay": delay_ms,
            "linkPreview": False,
        }
        async with httpx.AsyncClient(timeout=45.0) as client:
            resp = await client.post(url, headers=self._headers(), json=payload)
            if resp.status_code >= 400:
                logger.error("sendText failed %s %s", resp.status_code, resp.text[:500])
                resp.raise_for_status()
            return resp.json()

    async def send_audio(self, phone: str, audio_bytes: bytes, delay_ms: int = 2500) -> dict:
        """Envia áudio (mp3/ogg) como mensagem de voz."""
        url = f"{self.base}/message/sendWhatsAppAudio/{self.instance}"
        b64 = base64.b64encode(audio_bytes).decode("ascii")
        payload = {
            "number": self._number(phone),
            "audio": b64,
            "delay": delay_ms,
            "encoding": True,
        }
        async with httpx.AsyncClient(timeout=90.0) as client:
            resp = await client.post(url, headers=self._headers(), json=payload)
            if resp.status_code >= 400:
                logger.error("sendWhatsAppAudio failed %s %s", resp.status_code, resp.text[:500])
                resp.raise_for_status()
            return resp.json()

    async def download_media(self, message_payload: dict[str, Any]) -> bytes:
        """Baixa mídia descriptografada (áudio) a partir do objeto da mensagem do webhook."""
        url = f"{self.base}/chat/getBase64FromMediaMessage/{self.instance}"
        payload = {
            "message": message_payload,
            "convertToMp4": False,
        }
        async with httpx.AsyncClient(timeout=90.0) as client:
            resp = await client.post(url, headers=self._headers(), json=payload)
            if resp.status_code >= 400:
                logger.error("getBase64FromMediaMessage failed %s %s", resp.status_code, resp.text[:500])
                resp.raise_for_status()
            data = resp.json()
            b64 = data.get("base64") or data.get("data") or ""
            if isinstance(b64, dict):
                b64 = b64.get("base64") or ""
            if "," in b64 and b64.strip().startswith("data:"):
                b64 = b64.split(",", 1)[1]
            if not b64:
                raise RuntimeError(f"base64 vazio no download de mídia: keys={list(data.keys())}")
            return base64.b64decode(b64)
