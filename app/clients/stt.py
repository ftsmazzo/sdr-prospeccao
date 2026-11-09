import logging

import httpx

from app.config import Settings

logger = logging.getLogger("edu.stt")


class SpeechToTextClient:
    """Transcrição via OpenRouter (Whisper)."""

    def __init__(self, settings: Settings):
        self.base = settings.openrouter_base_url.rstrip("/")
        self.api_key = settings.openrouter_api_key
        self.model = settings.stt_model

    async def transcribe(self, audio_bytes: bytes, filename: str = "audio.ogg") -> str:
        if not self.api_key:
            raise RuntimeError("OPENROUTER_API_KEY não configurada")

        url = f"{self.base}/audio/transcriptions"
        headers = {"Authorization": f"Bearer {self.api_key}"}
        files = {"file": (filename, audio_bytes, "audio/ogg")}
        data = {"model": self.model, "language": "pt"}

        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(url, headers=headers, files=files, data=data)
            if resp.status_code >= 400:
                logger.error("stt failed %s %s", resp.status_code, resp.text[:500])
                resp.raise_for_status()
            payload = resp.json()
            text = (payload.get("text") or "").strip()
            logger.info("stt ok chars=%s", len(text))
            return text
