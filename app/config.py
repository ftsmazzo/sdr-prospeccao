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
    # Padrão demo-v2. Alternativa mais barata: openai/gpt-4.1-mini (só trocar OPENROUTER_MODEL).
    openrouter_model: str = "anthropic/claude-sonnet-5"
    briefing_model: str = "openai/gpt-4.1-mini"
    stt_model: str = "openai/whisper-1"
    # Histórico bruto no prompt (Redis guarda memory_max_messages).
    prompt_history_messages: int = 12
    # WhatsApp: números internos que recebem notificação de handoff/matrícula
    handoff_notify_numbers: str = "5516996282630"
    handoff_notify_on_matricula: bool = True

    evolution_base_url: str = ""
    evolution_api_key: str = ""
    evolution_instance: str = "poli"
    # false = envia OGG Opus como PTT sem re-encode (melhor p/ nota de voz já processada)
    evolution_audio_encoding: bool = False

    # Nome/gênero exibidos ao lead (projeto interno continua "Edu SDR")
    agent_name: str = "Edu"
    agent_gender: str = "f"  # "f" | "m"

    elevenlabs_api_key: str = ""
    elevenlabs_voice_id: str = ""
    elevenlabs_model_id: str = "eleven_v4"
    elevenlabs_stability: float = 0.35
    elevenlabs_similarity: float = 0.75
    elevenlabs_style: float = 0.0
    elevenlabs_speed: float = 1.0

    human_idle_min_ms: int = 10000
    human_idle_max_ms: int = 15000
    typing_min_ms: int = 2500
    typing_max_ms: int = 6000
    reply_delay_min_ms: int = 3200
    reply_delay_max_ms: int = 7000

    followup_delay_seconds: int = 900
    inbound_debounce_seconds: float = 7.0
    handoff_max_objecoes: int = 3

    # Fase 4 — envio ativo / retomada / demo
    demo_fast_followup: bool = False
    active_send_daily_limit: int = 50
    active_send_min_gap_seconds: int = 30
    active_send_max_gap_seconds: int = 120
    primeiro_contato_delay_seconds: int = 45

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
