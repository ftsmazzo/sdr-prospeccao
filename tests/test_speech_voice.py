"""Voz: tags, EAD, dados pessoais → texto."""

from __future__ import annotations

from app.orchestrator import AUDIO_KEY_HINTS, Orchestrator
from app.speech import (
    asks_or_confirms_personal_data,
    contains_link,
    phonetize_for_tts,
    sanitize_expression_tags,
    scrub_for_tts,
)


def test_scrub_phonetize_preserva_tags_e_ead():
    raw = "[chuckles] O diploma EAD vale igual. [thoughtful] Me conta."
    scrubbed = scrub_for_tts(raw)
    assert "[chuckles]" in scrubbed
    assert "[thoughtful]" in scrubbed
    out = phonetize_for_tts(scrubbed)
    assert "[chuckles]" in out
    assert "[thoughtful]" in out
    assert "ead" in out.lower()
    assert "E A D" not in out


def test_clamp_max_2_e_whitelist():
    text = "[chuckles] oi [thoughtful] tá [sighs] né [chuckles] fim"
    out = sanitize_expression_tags(text, allow_tags=True)
    assert out.count("[chuckles]") + out.count("[thoughtful]") == 2
    assert "[sighs]" not in out
    assert out.index("[chuckles]") < out.index("[thoughtful]")


def test_clamp_allow_false_remove_todas():
    text = "[chuckles] Me passa o CPF [thoughtful] por favor"
    out = sanitize_expression_tags(text, allow_tags=False)
    assert "[chuckles]" not in out
    assert "[thoughtful]" not in out


def test_personal_data_e_link_helpers():
    assert asks_or_confirms_personal_data(
        "Me manda nome completo, CPF e data de nascimento"
    )
    assert asks_or_confirms_personal_data("Confirma o cpf pra mim?")
    assert not asks_or_confirms_personal_data("Qual área você tá pensando?")
    assert contains_link("Aqui: https://exemplo.com/x")
    assert not contains_link("Sem link aqui")


def test_audio_key_hints_sem_matricul():
    assert "matricul" not in AUDIO_KEY_HINTS


class _FakeSettings:
    elevenlabs_api_key = ""
    elevenlabs_voice_id = ""
    agent_name = "Edu"
    agent_gender = "f"
    evolution_audio_encoding = False
    human_idle_min_ms = 1
    human_idle_max_ms = 1
    typing_min_ms = 1
    typing_max_ms = 1
    reply_delay_min_ms = 1
    reply_delay_max_ms = 1
    handoff_max_objecoes = 3
    followup_delay_seconds = 900
    inbound_debounce_seconds = 7
    memory_ttl_seconds = 60
    memory_max_messages = 10
    public_base_url = "http://localhost"
    openrouter_api_key = ""
    openrouter_base_url = ""
    openrouter_model = "x"
    stt_model = "x"
    evolution_base_url = ""
    evolution_api_key = ""
    evolution_instance = "x"
    elevenlabs_model_id = "eleven_v4"
    elevenlabs_stability = 0.35
    elevenlabs_similarity = 0.75
    elevenlabs_style = 0.0
    elevenlabs_speed = 1.0
    app_env = "test"
    webhook_secret = ""
    webhook_secret_enforce = False
    database_url = ""
    redis_url = ""
    regras_path = "prompts/regras.md"
    conhecimento_path = "prompts/conhecimento_lead.md"
    knowledge_path = "docs/CONHECIMENTO-AGENTE-FAVENI.md"


def test_should_reply_audio_false_para_cpf_e_link(monkeypatch):
    settings = _FakeSettings()
    settings.elevenlabs_api_key = "x"
    settings.elevenlabs_voice_id = "y"
    orch = Orchestrator(settings)  # type: ignore[arg-type]
    monkeypatch.setattr(
        orch.memory,
        "get_meta",
        lambda _phone: {"consecutive_audio_out": 0},
    )
    assert (
        orch._should_reply_audio(
            phone="5511999999999",
            inbound_was_audio=True,
            reply="Me manda por escrito nome completo, CPF e data de nascimento.",
            course=None,
        )
        is False
    )
    assert (
        orch._should_reply_audio(
            phone="5511999999999",
            inbound_was_audio=True,
            reply="Segue o link https://exemplo.com/checkout/x",
            course="Pós",
        )
        is False
    )


def test_allow_expression_tags_handoff_e_irritado():
    orch = Orchestrator(_FakeSettings())  # type: ignore[arg-type]
    assert (
        orch._allow_expression_tags(
            {"etapa": "handoff_humano"},
            "Vou te passar para um especialista.",
            False,
        )
        is False
    )
    assert (
        orch._allow_expression_tags(
            {"etapa": "recomendacao"},
            "Faz sentido essa dúvida.",
            True,
        )
        is False
    )
    assert (
        orch._allow_expression_tags(
            {"etapa": "recomendacao"},
            "Me confirma o CPF?",
            False,
        )
        is False
    )
    assert (
        orch._allow_expression_tags(
            {"etapa": "recomendacao"},
            "O diploma vale igualzinho.",
            False,
        )
        is True
    )
