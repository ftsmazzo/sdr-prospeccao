"""Execução de pending_offer sem LLM (caminho código)."""

from __future__ import annotations

from types import SimpleNamespace

from app.lead_state import ensure_lead_state
from app.offers import infer_offer_from_reply
from app.orchestrator import Orchestrator
from app.schemas import AgentResponse, OfferPayload


class _Mem:
    def __init__(self):
        self._meta: dict = {}
        self._hist: list = []

    def get_meta(self, phone: str) -> dict:
        return self._meta.setdefault(phone, {})

    def set_meta(self, phone: str, meta: dict) -> None:
        self._meta[phone] = meta

    def get_history(self, phone: str) -> list:
        return list(self._hist)

    def append(self, phone: str, role: str, content: str) -> None:
        self._hist.append({"role": role, "content": content})

    def clear(self, phone: str) -> None:
        self._meta.pop(phone, None)
        self._hist.clear()


def _orch() -> Orchestrator:
    settings = SimpleNamespace(
        openrouter_api_key="x",
        openrouter_base_url="http://x",
        openrouter_model="test",
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
    orch = Orchestrator(settings)  # type: ignore[arg-type]
    orch.memory = _Mem()  # type: ignore[assignment]
    return orch


def test_save_pending_infers_from_reply():
    orch = _orch()
    meta: dict = {}
    agent = AgentResponse(
        reply="Quer que eu registre seu pedido para um especialista?",
        offer=None,
    )
    orch._save_pending_offer(meta, agent)
    assert meta.get("pending_offer", {}).get("type") == "encaminhamento"


def test_execute_contrato_sets_fechamento():
    orch = _orch()
    meta: dict = {}
    ls = ensure_lead_state(meta)
    ls["curso_escolhido"] = "Autismo"
    ls["graduacao"] = "concluida"
    ls["aluno_e_terceiro"] = True
    meta["lead_state"] = ls
    reply, course, _ = orch._execute_pending_contrato(meta)
    assert meta["etapa"] == "fechamento"
    assert meta["lead_state"]["aceite_matricula"] is True
    assert "dela/dele" in reply or "nome completo" in reply
    assert meta.get("pending_offer") is None
    assert course == "Autismo"


def test_offer_payload_roundtrip():
    a = AgentResponse(
        reply="ok",
        offer=OfferPayload(type="contrato"),
    )
    assert a.offer and a.offer.type == "contrato"
    assert infer_offer_from_reply(a.reply) is None
