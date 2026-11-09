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

    evolution_base_url: str = ""
    evolution_api_key: str = ""
    evolution_instance: str = "poli"

    knowledge_path: str = "docs/CONHECIMENTO-AGENTE-FAVENI.md"


@lru_cache
def get_settings() -> Settings:
    return Settings()
