"""Correções 0.9.4: TTS Maria, dados sem re-pedir, handoff sem sair do funil."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from app.lead_data import (
    apply_extracted_contract_fields,
    extract_contract_fields_from_text,
)
from app.lead_state import ensure_lead_state
from app.offers import contract_data_request_reply
from app.orchestrator import Orchestrator
from app.speech import (
    spoken_has_foreign_person_name,
    strip_wrong_person_vocatives,
)


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
        handoff_notify_numbers="",
        handoff_store_path="",
    )
    orch = Orchestrator(settings)  # type: ignore[arg-type]
    orch.memory = _Mem()  # type: ignore[assignment]
    return orch


def test_strip_maria_vocative_from_spoken():
    spoken = "[chuckles] Ah, Maria, faz total sentido essa dúvida sobre o cartão."
    allowed = {"frederico"}
    assert spoken_has_foreign_person_name(spoken, allowed_names=allowed)
    cleaned = strip_wrong_person_vocatives(spoken, allowed_names=allowed)
    assert "Maria" not in cleaned
    assert "maria" not in cleaned.casefold()
    assert not spoken_has_foreign_person_name(cleaned, allowed_names=allowed)
    # Se o lead for Maria, mantém
    keep = strip_wrong_person_vocatives(spoken, allowed_names={"maria", "frederico"})
    assert "Maria" in keep
    # Mariana não pode ser cortada como Maria
    mariana = "Ah, Mariana, faz sentido pagar no cartão."
    kept_m = strip_wrong_person_vocatives(mariana, allowed_names={"mariana"})
    assert "Mariana" in kept_m
    assert not spoken_has_foreign_person_name(mariana, allowed_names={"mariana"})


def test_birth_date_needs_context_or_cpf_block():
    loose = extract_contract_fields_from_text("quero até 15/03/2026 pra começar")
    assert "birth_date" not in loose
    stacked = extract_contract_fields_from_text(
        "Frederico Mazzo\n529.982.247-25\n12/03/1990"
    )
    assert stacked.get("birth_date") == "12/03/1990"
    labeled = extract_contract_fields_from_text("nascimento: 01/05/1985")
    assert labeled.get("birth_date") == "01/05/1985"


def test_contract_grammar_seu_sua():
    meta: dict = {"full_name": "Frederico Mazzo"}
    ls = {"nome": "Frederico Mazzo"}
    text = contract_data_request_reply(meta, ls)
    assert "data de nascimento seu" not in text.casefold()
    assert "o seu CPF" in text
    assert "a sua data de nascimento" in text


def test_pending_contrato_three_fields_schedules(monkeypatch):
    orch = _orch()
    phone = "5516996480805"
    scheduled: dict = {}

    def _fake_schedule(**kwargs):
        scheduled.update(kwargs)
        return {"id": "job-1", **kwargs}

    monkeypatch.setattr(
        "app.orchestrator.get_scheduler",
        lambda: SimpleNamespace(schedule_document=_fake_schedule),
    )

    meta: dict = {}
    ls = ensure_lead_state(meta)
    ls["curso_escolhido"] = "Autismo"
    ls["graduacao"] = "concluida"
    meta["lead_state"] = ls
    meta["pending_offer"] = {"type": "contrato", "created_turn": 1}
    meta["etapa"] = "recomendacao"

    msg = "Frederico Mazzo\n529.982.247-25\n12/03/1990"
    extracted = extract_contract_fields_from_text(msg)
    assert set(extracted) >= {"full_name", "cpf", "birth_date"}
    apply_extracted_contract_fields(meta, ls, extracted)

    reply, course, delivery = orch._execute_pending_contrato(
        meta, push_name="Frederico", phone=phone
    )
    assert delivery is True
    assert course == "Autismo"
    assert "me passa" not in reply.casefold()
    assert "cpf" not in reply.casefold()
    assert meta.get("pending_contract") is True
    assert meta.get("pending_offer") is None
    assert scheduled.get("phone") == phone
    assert scheduled.get("cpf") == "52998224725"
    assert scheduled.get("with_checkout") is True


def test_encaminhamento_keeps_fechamento_and_job(monkeypatch):
    orch = _orch()
    phone = "5516996480805"
    jobs: list[dict] = []

    def _fake_schedule(**kwargs):
        job = {"id": "job-doc", "type": "send_contrato", **kwargs}
        jobs[:] = [job]
        return job

    def _fake_list():
        return list(jobs)

    monkeypatch.setattr(
        "app.orchestrator.get_scheduler",
        lambda: SimpleNamespace(
            schedule_document=_fake_schedule,
            list_pending=_fake_list,
            clear_for_phone=lambda _p: 0,
        ),
    )
    monkeypatch.setattr(
        "app.orchestrator.register_handoff_request",
        lambda **_kw: {"id": "h-1"},
    )
    def _fake_create_task(coro, *args, **kwargs):
        if hasattr(coro, "close"):
            coro.close()
        return MagicMock()

    monkeypatch.setattr(
        "app.orchestrator.asyncio.create_task",
        _fake_create_task,
    )

    meta: dict = {}
    ls = ensure_lead_state(meta)
    ls["curso_escolhido"] = "Autismo"
    ls["nome"] = "Frederico Mazzo"
    ls["aceite_matricula"] = True
    meta["lead_state"] = ls
    meta["etapa"] = "fechamento"
    meta["full_name"] = "Frederico Mazzo"
    meta["cpf"] = "52998224725"
    meta["birth_date"] = "12/03/1990"
    meta["pending_contract"] = True
    meta["course"] = "Autismo"

    # Job de contrato já agendado
    get_sched = __import__("app.orchestrator", fromlist=["get_scheduler"]).get_scheduler
    get_sched().schedule_document(
        phone=phone,
        lead_name="Frederico Mazzo",
        cpf="52998224725",
        birth_date="12/03/1990",
        course="Autismo",
        with_checkout=True,
    )
    assert jobs and jobs[0]["id"] == "job-doc"

    reply, course, delivery = orch._execute_pending_encaminhamento(
        phone,
        meta,
        push_name="Frederico",
        motivo="pagamento_cartao",
    )
    assert meta["etapa"] == "fechamento"
    assert meta["pending_contract"] is True
    assert jobs and jobs[0]["id"] == "job-doc"
    assert "registrei" in reply.casefold() or "especialista" in reply.casefold()
    assert course is None
    assert delivery is False


def test_register_handoff_keeps_fechamento(monkeypatch):
    orch = _orch()
    phone = "5516996480805"

    def _fake_create_task(coro, *args, **kwargs):
        if hasattr(coro, "close"):
            coro.close()
        return MagicMock()

    monkeypatch.setattr(
        "app.orchestrator.register_handoff_request",
        lambda **_kw: {"id": "h-2"},
    )
    monkeypatch.setattr(
        "app.orchestrator.asyncio.create_task",
        _fake_create_task,
    )

    from app.schemas import AgentResponse

    meta: dict = {}
    ls = ensure_lead_state(meta)
    ls["curso_escolhido"] = "Autismo"
    ls["nome"] = "Frederico Mazzo"
    ls["aceite_matricula"] = True
    meta["lead_state"] = ls
    meta["etapa"] = "fechamento"
    meta["pending_contract"] = True
    meta["handoff_registrado"] = False

    agent = AgentResponse(
        reply="Vou registrar sua dúvida sobre o cartão.",
        action="REGISTER_HANDOFF",
        action_data={"motivo": "pagamento_cartao"},
    )
    orch._apply_actions(
        phone,
        meta,
        agent,
        "Frederico",
        user_text="Sim, pode registrar",
        last_assistant=(
            "Quer que eu registre seu pedido para um especialista "
            "sobre pagamento no cartão?"
        ),
    )
    assert meta["etapa"] == "fechamento"
    assert meta["pending_contract"] is True
    assert meta.get("handoff_registrado") is True
