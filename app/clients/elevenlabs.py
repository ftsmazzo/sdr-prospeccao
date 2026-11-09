import logging

import httpx

from app.config import Settings

logger = logging.getLogger("edu.elevenlabs")


class ElevenLabsClient:
    def __init__(self, settings: Settings):
        self.api_key = settings.elevenlabs_api_key
        self.voice_id = settings.elevenlabs_voice_id
        self.model_id = settings.elevenlabs_model_id
        self.stability = settings.elevenlabs_stability
        self.similarity = settings.elevenlabs_similarity
        self.style = settings.elevenlabs_style
        self.speed = settings.elevenlabs_speed

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
            "voice_settings": {
                # stability mais baixo = mais variação emocional (menos monótono)
                "stability": self.stability,
                "similarity_boost": self.similarity,
                # style > 0 exagera um pouco o “jeito” da voz (mais vivo)
                "style": self.style,
                "use_speaker_boost": True,
                "speed": self.speed,
            },
        }
        # language_code só em modelos v3/v4 (não no multilingual_v2)
        if self.model_id.startswith("eleven_v"):
            payload["language_code"] = "pt"

        async with httpx.AsyncClient(timeout=90.0) as client:
            resp = await client.post(
                url,
                headers=headers,
                params={"output_format": "mp3_44100_128"},
                json=payload,
            )
            if resp.status_code >= 400:
                logger.error("elevenlabs failed %s %s", resp.status_code, resp.text[:500])
                resp.raise_for_status()
            return resp.content
