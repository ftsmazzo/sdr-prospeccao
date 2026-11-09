from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"
    public_base_url: str = "https://sdr-prospeccao-api.kxryyk.easypanel.host"
    webhook_secret: str = ""
    # false = aceita e só avisa no log; true = 401 se secret inválido
    webhook_secret_enforce: bool = False

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
    elevenlabs_model_id: str = "eleven_v4"
    elevenlabs_stability: float = 0.4
    elevenlabs_similarity: float = 0.75
    elevenlabs_style: float = 0.1
    elevenlabs_speed: float = 1.05

    human_idle_min_ms: int = 10000
    human_idle_max_ms: int = 15000
    typing_min_ms: int = 2500
    typing_max_ms: int = 6000
    reply_delay_min_ms: int = 3200
    reply_delay_max_ms: int = 7000

    followup_delay_seconds: int = 900
    inbound_debounce_seconds: float = 7.0

    # TTL memória conversa/meta (segundos) — 30 dias
    memory_ttl_seconds: int = 60 * 60 * 24 * 30
    memory_max_messages: int = 30

    regras_path: str = "prompts/regras.md"
    conhecimento_path: str = "prompts/conhecimento_lead.md"
    # legado / stub
    knowledge_path: str = "docs/CONHECIMENTO-AGENTE-FAVENI.md"


@lru_cache
def get_settings() -> Settings:
    return Settings()
