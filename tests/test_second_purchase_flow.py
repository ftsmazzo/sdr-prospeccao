"""E2E unitário: 2ª compra (esposa) com LLM mock — sem API."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

from app.briefing import build_briefing_user_payload, refresh_briefing, scrub_sensitive
from app.compra_atual import ensure_compra_atual, format_compra_atual_block
from app.lead_state import begin_new_purchase, ensure_lead_state
from app.notify import (
    build_handoff_notify_message,
    build_matricula_notify_message,
    is_internal_number,
    parse_notify_numbers,
)
from app.offers import (
    classify_offer_response_fallback,
    infer_offer_from_reply,
    lead_affirms_offer,
)
from app.orchestrator import Orchestrator
from app.schemas import AgentResponse, OfferPayload


class _Mem:
    def __init__(self):
        self._meta: dict[str, dict] = {}
        self._hist: dict[str, list] = {}

    def get_meta(self, phone: str) -> dict:
        return self._meta.setdefault(phone, {})

    def set_meta(self, phone: str, meta: dict) -> None:
        self._meta[phone] = meta

    def get_history(self, phone: str) -> list:
        return list(self._hist.setdefault(phone, []))

    def append(self, phone: str, role: str, content: str) -> None:
        self._hist.setdefault(phone, []).append({"role": role, "content": content})

    def replace_history(self, phone: str, history: list) -> None:
        self._hist[phone] = list(history)


class _FakeLLM:
    def __init__(self, queue: list[AgentResponse | str]):
        self.queue = list(queue)
        self.calls: list[Any] = []

    async def chat(self, messages, temperature=0.6, *, model=None):
        self.calls.append(("chat", model, messages))
        item = self.queue.pop(0) if self.queue else "Lead: Frederico\nDecisões: ok"
        if isinstance(item, AgentResponse):
            return item.reply
        return str(item)

    async def chat_tool(self, messages, *, tools, tool_choice, temperature=0.4):
        self.calls.append(("tool", messages))
        item = self.queue.pop(0)
        if isinstance(item, AgentResponse):
            return item.model_dump_json()
        return str(item)


def _settings(**extra):
    base = dict(
        openrouter_api_key="x",
        openrouter_base_url="http://x",
        openrouter_model="test",
        briefing_model="openai/gpt-4.1-mini",
        prompt_history_messages=12,
        handoff_notify_numbers="5516996282630",
        handoff_notify_on_matricula=True,
        stt_model="openai/whisper-1",
        redis_url="",
        evolution_base_url="http://sim.invalid",
        evolution_api_key="sim",
        evolution_instance="poli",
        evolution_audio_encoding=False,
        agent_name="Clara",
        agent_gender="f",
        elevenlabs_api_key="",
        elevenlabs_voice_id="",
        elevenlabs_model_id="eleven_v4",
        elevenlabs_stability=0.35,
        elevenlabs_similarity=0.75,
        elevenlabs_style=0.0,
        elevenlabs_speed=1.0,
        public_base_url="http://localhost",
        handoff_max_objecoes=3,
        human_idle_min_ms=0,
        human_idle_max_ms=0,
        typing_min_ms=0,
        typing_max_ms=0,
        memory_ttl_seconds=60,
        memory_max_messages=30,
        followup_delay_seconds=900,
    )
    base.update(extra)
    return SimpleNamespace(**base)


def _orch(llm_queue: list) -> Orchestrator:
    orch = Orchestrator(_settings())  # type: ignore[arg-type]
    orch.memory = _Mem()  # type: ignore[assignment]
    orch.llm = _FakeLLM(llm_queue)  # type: ignore[assignment]
    return orch


def test_adoraria_affirms_fallback():
    assert lead_affirms_offer("Adoraria") is True
    assert classify_offer_response_fallback("Adoraria") == "aceitou"


def test_infer_matricula_offer_reserva():
    assert infer_offer_from_reply(
        "Quer seguir com a matrícula da sua esposa agora?"
    ) == {"type": "contrato"}


def test_save_pending_from_json_before_audio_path():
    orch = _orch([])
    meta: dict = {}
    agent = AgentResponse(
        reply="Quer que eu prepare o contrato da sua esposa?",
        offer=OfferPayload(type="contrato"),
    )
    orch._save_pending_offer(meta, agent)
    assert meta["pending_offer"]["type"] == "contrato"


def test_e2e_esposa_adoraria_preserves_autismo():
    phone = "5516996480805"
    orch = _orch([])
    mem: _Mem = orch.memory  # type: ignore[assignment]
    meta = mem.get_meta(phone)
    meta["matriculas"] = [
        {
            "curso": "Autismo",
            "aluno_nome": "Frederico Mazzo",
            "status": "confirmada",
        }
    ]
    meta["full_name"] = "Frederico Mazzo"
    meta["course"] = "Autismo"
    meta["pending_offer"] = {"type": "contrato", "created_turn": 1}
    ls = ensure_lead_state(meta)
    meta["etapa"] = "recomendacao"
    ls["nome"] = "Frederico Mazzo"
    ls["aluno_e_terceiro"] = True
    ls["aluno_relacao"] = "esposa"
    ls["aluno_genero"] = "f"
    ls["graduacao"] = "concluida"
    ls["area_interesse"] = "gestão"
    ls["curso_escolhido"] = "MBA Executivo em Gestão de Clínicas e Consultórios"
    ls["curso_recomendado"] = "MBA Executivo em Gestão de Clínicas e Consultórios"
    meta["lead_state"] = ls
    ca = ensure_compra_atual(meta)
    ca.update(
        {
            "aluno_e_terceiro": True,
            "aluno_relacao": "esposa",
            "aluno_genero": "f",
            "graduacao_aluno": "concluida",
            "interesse_aluno": "gestão",
            "curso_escolhido": "MBA Executivo em Gestão de Clínicas e Consultórios",
            "curso_recomendado": "MBA Executivo em Gestão de Clínicas e Consultórios",
        }
    )
    meta["compra_atual"] = ca
    mem.set_meta(phone, meta)

    assert classify_offer_response_fallback("Adoraria") == "aceitou"
    reply, course, _ = orch._execute_pending_contrato(meta, push_name="Frederico")
    assert meta["etapa"] == "fechamento"
    assert "dela" in reply.casefold() or "esposa" in reply.casefold()
    assert "dela/dele" not in reply
    assert meta["matriculas"][0]["curso"] == "Autismo"
    assert course


def test_begin_new_purchase_preserves_compra_atual_fields():
    meta: dict = {
        "matriculas": [{"curso": "Autismo", "aluno_nome": "Frederico", "status": "confirmada"}],
        "course": "Autismo",
        "full_name": "Frederico",
    }
    ls = ensure_lead_state(meta)
    meta["etapa"] = "matriculado"
    ls["aluno_e_terceiro"] = True
    ls["aluno_relacao"] = "esposa"
    ls["aluno_genero"] = "f"
    begin_new_purchase(meta, ls)
    assert meta["etapa"] == "qualificacao"
    # 1ª abertura zera graduação do comprador
    assert ls.get("graduacao") is None
    # Preenche compra_atual e chama de novo — não pode apagar
    ca = meta["compra_atual"]
    ca["graduacao_aluno"] = "concluida"
    ca["interesse_aluno"] = "gestão"
    ca["curso_recomendado"] = "MBA Executivo em Gestão de Clínicas e Consultórios"
    ls["graduacao"] = "concluida"
    ls["area_interesse"] = "gestão"
    ls["curso_recomendado"] = "MBA Executivo em Gestão de Clínicas e Consultórios"
    meta["etapa"] = "matriculado"  # força caminho reopen
    begin_new_purchase(meta, ls)
    assert meta["compra_atual"]["graduacao_aluno"] == "concluida"
    assert meta["compra_atual"]["interesse_aluno"] == "gestão"
    assert meta["matriculas"][0]["curso"] == "Autismo"
    assert "gestão" in format_compra_atual_block(meta["compra_atual"]).casefold()


def test_handoff_notify_sem_cpf():
    msg = build_handoff_notify_message(
        agent_name="Clara",
        lead_nome="Frederico",
        lead_phone="5516996480805",
        motivo="data de vencimento da mensalidade",
        curso="Autismo",
        etapa="matriculado",
        briefing="Lead Frederico, CPF 123.456.789-00 nasc 01/01/1990, curso Autismo.",
    )
    assert "123.456.789-00" not in msg
    assert "01/01/1990" not in msg
    assert "Frederico" in msg
    assert "5516996480805" in msg
    assert "Novo encaminhamento — Clara" in msg
    mat = build_matricula_notify_message(
        agent_name="Clara",
        lead_nome="Ana",
        lead_phone="5516996480805",
        curso="Enfermagem em Estética",
    )
    assert "CPF" not in mat
    assert "Ana" in mat
    assert parse_notify_numbers("5516996282630, 55 16 99628-2630") == [
        "5516996282630"
    ]
    assert is_internal_number("5516996282630", ["5516996282630"])


def test_briefing_refresh_and_scrub():
    assert "[dado omitido]" in scrub_sensitive("CPF 123.456.789-00 ok")

    class _LLM:
        async def chat(self, messages, temperature=0.2, *, model=None):
            return (
                "Lead/aluno: Frederico comprando para esposa\n"
                "Decisões: curso gestão\n"
                "Ofertas: contrato — Adoraria\n"
                "Pendências: pedir dados dela\n"
                "Matrículas: Autismo (Frederico)"
            )

    out = asyncio.run(
        refresh_briefing(
            _LLM(),
            previous="",
            recent_messages=[
                {"role": "user", "content": "Adoraria"},
                {"role": "assistant", "content": "Me passa o CPF 111.222.333-44"},
            ],
            matriculas=[{"curso": "Autismo", "aluno_nome": "Frederico"}],
            model="openai/gpt-4.1-mini",
        )
    )
    assert "esposa" in out.casefold() or "Frederico" in out
    assert "111.222.333-44" not in out
    payload = build_briefing_user_payload(
        previous="antigo",
        recent_messages=[{"role": "user", "content": "oi"}],
    )
    assert "Briefing anterior" in payload
