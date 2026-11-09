import logging

import httpx

from app.config import Settings

logger = logging.getLogger("edu.elevenlabs")


class ElevenLabsClient:
    def __init__(self, settings: Settings):
        self.api_key = settings.elevenlabs_api_key
        self.voice_id = settings.elevenlabs_voice_id
        self.model_id = settings.elevenlabs_model_id

    @property
    def enabled(self) -> bool:
        return bool(self.api_key and self.voice_id)

    async def synthesize(self, text: str) -> bytes:
        if not self.enabled:
            raise RuntimeError("ElevenLabs não configurado")

        url = f"https://api.elevenlabs.io/v1/text-to-speech/{self.voice_id}"
        headers = {
            "xi-api-key": self.api_key,
            "Content-Type": "application/json",
            "Accept": "audio/mpeg",
        }
        payload = {
            "text": text,
            "model_id": self.model_id,
            "language_code": "pt",
        }
        async with httpx.AsyncClient(timeout=90.0) as client:
            resp = await client.post(url, headers=headers, json=payload)
            if resp.status_code >= 400:
                logger.error("elevenlabs failed %s %s", resp.status_code, resp.text[:400])
                resp.raise_for_status()
            return resp.content
