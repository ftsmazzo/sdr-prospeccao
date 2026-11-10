"""Regeneração de reply: promessa, CPF cedo, anti-repetição, stock sem duplicar."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.orchestrator import Orchestrator, replies_nearly_equal, reply_has_scarcity
from app.schemas import AgentResponse


class _FakeMemory:
    def __init__(self) -> None:
        self._meta: dict = {}
        self._hist: dict[str, list] = {}

    def get_meta(self, phone: str) -> dict:
        return self._meta.setdefault(phone, {})

    def set_meta(self, phone: str, meta: dict) -> None:
        self._meta[phone] = meta

    def get_history(self, phone: str) -> list:
        return list(self._hist.get(phone, []))

    def append(self, phone: str, role: str, content: str) -> None:
        self._hist.setdefault(phone, []).append({"role": role, "content": content})

    def clear(self, phone: str) -> bool:
        self._hist.pop(phone, None)
        self._meta.pop(phone, None)
        return True


def _orch() -> Orchestrator:
    settings = SimpleNamespace(
        openrouter_api_key="x",
        openrouter_base_url="http://x",
        openrouter_model="test",
        evolution_base_url="http://sim.invalid",
        evolution_api_key="sim",
        evolution_instance="x",
        evolution_audio_encoding=False,
        elevenlabs_api_key="",
        elevenlabs_voice_id="",
        elevenlabs_model_id="eleven_v4",
        elevenlabs_stability=0.35,
        elevenlabs_similarity=0.75,
        elevenlabs_style=0.0,
        elevenlabs_speed=1.0,
        human_idle_min_ms=0,
        human_idle_max_ms=0,
        typing_min_ms=0,
        typing_max_ms=0,
        reply_delay_min_ms=0,
        reply_delay_max_ms=0,
        followup_delay_seconds=900,
        inbound_debounce_seconds=7,
        handoff_max_objecoes=3,
        memory_ttl_seconds=60,
        memory_max_messages=30,
        public_base_url="http://localhost",
        agent_name="Clara",
        agent_gender="f",
        stt_model="x",
        app_env="test",
        webhook_secret="",
        webhook_secret_enforce=False,
        database_url="",
        redis_url="",
        regras_path="prompts/regras.md",
        conhecimento_path="prompts/conhecimento_lead.md",
        knowledge_path="docs/CONHECIMENTO-AGENTE-FAVENI.md",
    )
    orch = Orchestrator(settings)  # type: ignore[arg-type]
    orch.memory = _FakeMemory()  # type: ignore[assignment]
    return orch


def test_replies_nearly_equal_and_scarcity():
    assert replies_nearly_equal("Oi tudo bem?", "Oi  tudo bem?")
    assert not replies_nearly_equal("Oi", "Qual curso você quer?")
    assert reply_has_scarcity("Vamos garantir sua vaga hoje")
    assert not reply_has_scarcity("A mensalidade é a partir de R$ 69,90")


def test_reply_needs_regen_promessa_e_cpf():
    orch = _orch()
    meta = {"etapa": "recomendacao", "lead_state": {"curso_escolhido": None, "aceite_matricula": False}}
    assert (
        orch._reply_needs_regen(
            "Vou preparar seu contrato agora",
            meta,
            delivery_ran=False,
            blocked_promise_reason=None,
            last_assistant="",
        )
        == "promessa_sem_acao"
    )
    assert (
        orch._reply_needs_regen(
            "Vou te chamar em alguns dias para acompanhar sua decisão",
            meta,
            delivery_ran=False,
            blocked_promise_reason=None,
            last_assistant="",
        )
        == "promessa_lembrete"
    )
    assert (
        orch._reply_needs_regen(
            "Me manda nome completo, CPF e data de nascimento?",
            meta,
            delivery_ran=False,
            blocked_promise_reason=None,
            last_assistant="",
        )
        == "dados_antes_fechamento"
    )
    assert (
        orch._reply_needs_regen(
            "Na matrícula você envia diploma e o CPF entra no contrato. Qual área te interessa?",
            meta,
            delivery_ran=False,
            blocked_promise_reason=None,
            last_assistant="",
        )
        is None
    )
    meta_fech = {"etapa": "fechamento", "lead_state": {}}
    assert (
        orch._reply_needs_regen(
            "Me manda nome completo, CPF e data de nascimento?",
            meta_fech,
            delivery_ran=False,
            blocked_promise_reason=None,
            last_assistant="",
        )
        is None
    )


def test_finalize_regen_limpa_nao_usa_stock():
    orch = _orch()
    phone = "sim:t1"
    meta = {
        "etapa": "recomendacao",
        "lead_state": {"curso_escolhido": "Enfermagem em Estética", "aceite_matricula": False},
    }
    orch.memory.set_meta(phone, meta)
    orch._call_agent_json = AsyncMock(  # type: ignore[method-assign]
        return_value=AgentResponse(
            reply="A pós é 100% online, a partir de R$ 69,90. Quantas horas por semana você teria?",
            state_update={},
            action=None,
            action_data={},
        )
    )
    out = asyncio.run(
        orch._finalize_reply(
            phone=phone,
            meta=meta,
            messages=[{"role": "user", "content": "me manda o resumo"}],
            reply="Vou preparar seu contrato e te mando o PDF",
            course=None,
            blocked_promise_reason="promessa_sem_acao",
            delivery_ran=False,
        )
    )
    assert "vou preparar" not in out.casefold()
    assert "horas por semana" in out.casefold()
    assert meta.get("last_stock_reply") is None
    orch._call_agent_json.assert_awaited()


def test_finalize_stock_nao_repete():
    orch = _orch()
    phone = "sim:t2"
    first_stock = "Antes de eu preparar o contrato, me confirma qual curso você quer seguir?"
    meta = {
        "etapa": "recomendacao",
        "lead_state": {"curso_escolhido": None, "aceite_matricula": False},
        "last_stock_reply": first_stock,
    }
    orch.memory.set_meta(phone, meta)
    orch._call_agent_json = AsyncMock(  # type: ignore[method-assign]
        return_value=AgentResponse(
            reply="Já te mando o link do contrato",
            state_update={},
            action=None,
            action_data={},
        )
    )
    out = asyncio.run(
        orch._finalize_reply(
            phone=phone,
            meta=meta,
            messages=[{"role": "user", "content": "quero o contrato"}],
            reply="Vou preparar seu contrato agora",
            course=None,
            blocked_promise_reason="promessa_sem_acao",
            delivery_ran=False,
        )
    )
    assert out != first_stock
    assert meta["last_stock_reply"] == out


def test_dois_stocks_seguidos_handoff_loop_stock():
    orch = _orch()
    phone = "sim:t-loop"
    meta = {
        "etapa": "recomendacao",
        "lead_state": {"curso_escolhido": None, "aceite_matricula": False},
        "stock_streak": 0,
    }
    orch.memory.set_meta(phone, meta)
    orch._call_agent_json = AsyncMock(  # type: ignore[method-assign]
        return_value=AgentResponse(
            reply="Já te mando o link do contrato",
            state_update={},
            action=None,
            action_data={},
        )
    )
    out1 = asyncio.run(
        orch._finalize_reply(
            phone=phone,
            meta=meta,
            messages=[{"role": "user", "content": "contrato"}],
            reply="Vou preparar seu contrato agora",
            course=None,
            blocked_promise_reason="promessa_sem_acao",
            delivery_ran=False,
        )
    )
    assert meta.get("etapa") != "handoff_humano"
    assert int(meta.get("stock_streak") or 0) == 1
    assert "especialista" not in out1.casefold()
    out2 = asyncio.run(
        orch._finalize_reply(
            phone=phone,
            meta=meta,
            messages=[{"role": "user", "content": "manda"}],
            reply="Vou preparar seu contrato agora",
            course=None,
            blocked_promise_reason="promessa_sem_acao",
            delivery_ran=False,
        )
    )
    assert meta.get("etapa") == "handoff_humano"
    assert meta.get("handoff_reason") == "loop_stock"
    assert "especialista" in out2.casefold()


def test_quase_igual_dispara_regen():
    orch = _orch()
    phone = "sim:t3"
    prev = "Perfeito — só pra eu seguir certo: você confirma que quer matricular em Enfermagem em Estética agora?"
    meta = {
        "etapa": "recomendacao",
        "lead_state": {
            "curso_escolhido": "Enfermagem em Estética",
            "aceite_matricula": False,
        },
    }
    orch.memory.append(phone, "assistant", prev)
    orch.memory.set_meta(phone, meta)
    orch._call_agent_json = AsyncMock(  # type: ignore[method-assign]
        return_value=AgentResponse(
            reply="Entendi que ainda quer analisar. Quantas horas por semana você teria?",
            state_update={},
            action=None,
            action_data={},
        )
    )
    out = asyncio.run(
        orch._finalize_reply(
            phone=phone,
            meta=meta,
            messages=[{"role": "user", "content": "ainda pensando"}],
            reply=prev,
            course=None,
            blocked_promise_reason=None,
            delivery_ran=False,
        )
    )
    assert "horas por semana" in out.casefold()
    orch._call_agent_json.assert_awaited()
