"""Isolamento de ambiente — chamar ANTES de importar app/."""

from __future__ import annotations

import os

SIM_EVOLUTION_BASE = "http://sim.invalid"


def apply_sim_env() -> None:
    os.environ["REDIS_URL"] = ""
    os.environ["ELEVENLABS_API_KEY"] = ""
    os.environ["ELEVENLABS_VOICE_ID"] = ""
    os.environ["EVOLUTION_BASE_URL"] = SIM_EVOLUTION_BASE
    os.environ["EVOLUTION_API_KEY"] = "sim"
    os.environ["HUMAN_IDLE_MIN_MS"] = "0"
    os.environ["HUMAN_IDLE_MAX_MS"] = "0"
    os.environ["TYPING_MIN_MS"] = "0"
    os.environ["TYPING_MAX_MS"] = "0"
    # Mesma identidade do deploy EasyPanel
    os.environ["AGENT_NAME"] = "Clara"
    os.environ["AGENT_GENDER"] = "f"
    # Evita worker de follow-up se algo importar main por acidente
    os.environ.setdefault("APP_ENV", "simulation")


def assert_sim_settings(settings) -> None:
    if settings.redis_url:
        raise SystemExit(
            f"ABORT sim: redis_url não está vazio ({settings.redis_url!r}). "
            "Isolation falhou."
        )
    if settings.evolution_base_url != SIM_EVOLUTION_BASE:
        raise SystemExit(
            f"ABORT sim: evolution_base_url={settings.evolution_base_url!r}, "
            f"esperado {SIM_EVOLUTION_BASE!r}."
        )
    if settings.elevenlabs_api_key or settings.elevenlabs_voice_id:
        raise SystemExit("ABORT sim: ElevenLabs ainda configurado — isolation falhou.")
