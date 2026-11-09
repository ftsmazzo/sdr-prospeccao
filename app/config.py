from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"
    public_base_url: str = "https://sdr-prospeccao-api.kxryyk.easypanel.host"
    webhook_secret: str = ""

    database_url: str = ""
    redis_url: str = ""

    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_model: str = "openai/gpt-4.1-mini"
    stt_model: str = "openai/whisper-1"

    evolution_base_url: str = ""
    evolution_api_key: str = ""
    evolution_instance: str = "poli"

    elevenlabs_api_key: str = ""
    elevenlabs_voice_id: str = ""
    # v4 = melhor qualidade; style alto = “vídeo de IA” (evitar)
    elevenlabs_model_id: str = "eleven_v4"
    # stability médio-baixo; style BAIXO; speed ~1.05 evita cadência pausada
    elevenlabs_stability: float = 0.4
    elevenlabs_similarity: float = 0.75
    elevenlabs_style: float = 0.1
    elevenlabs_speed: float = 1.05

    # delay humanizado (ms) — typing + envio
    reply_delay_min_ms: int = 3200
    reply_delay_max_ms: int = 7000

    knowledge_path: str = "docs/CONHECIMENTO-AGENTE-FAVENI.md"


@lru_cache
def get_settings() -> Settings:
    return Settings()
