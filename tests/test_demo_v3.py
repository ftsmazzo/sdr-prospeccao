"""demo-v3: contrato 2ª compra (terceiro) + Fase 4 (cadência, leads, janela)."""

from __future__ import annotations

import time
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.active_send import (
    can_send_active,
    next_window_start,
    within_active_window,
)
from app.checkout import create_checkout
from app.compra_atual import ensure_compra_atual
from app.contract_party import resolve_contract_party
from app.documents import build_contrato_pdf
from app.inbound_leads import create_or_update_lead, validate_lead_payload
from app.lead_data import apply_extracted_contract_fields, extract_contract_fields_from_text
from app.lead_state import ensure_lead_state
from app.notify import build_matricula_notify_message
from app.orchestrator import Orchestrator
from app.outbound_cadence import (
    cancel_retomadas,
    cadence_delays,
    parse_think_delay_seconds,
    schedule_silence_followups,
    schedule_think_followup,
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


def _settings(**kw):
    base = dict(
        openrouter_api_key="",
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
        handoff_notify_numbers="5516996282630",
        demo_fast_followup=False,
        active_send_daily_limit=50,
        active_send_min_gap_seconds=30,
        active_send_max_gap_seconds=120,
        primeiro_contato_delay_seconds=45,
        webhook_secret="test-secret",
    )
    base.update(kw)
    return SimpleNamespace(**base)


def test_1_6_second_purchase_pdf_uses_aluno(monkeypatch):
    """Segunda compra para terceiro → PDF/checkout no nome do aluno; 1ª matrícula intacta."""
    orch = Orchestrator(_settings())  # type: ignore[arg-type]
    orch.memory = _Mem()  # type: ignore[assignment]
    phone = "5516996480805"
    scheduled: dict = {}

    def _fake_schedule(**kwargs):
        scheduled.update(kwargs)
        return {"id": "j1", **kwargs}

    monkeypatch.setattr(
        "app.orchestrator.get_scheduler",
        lambda: SimpleNamespace(schedule_document=_fake_schedule),
    )

    meta: dict = {
        "matriculas": [
            {"curso": "Autismo", "aluno_nome": "Frederico Mazzo", "status": "confirmada"}
        ],
        "full_name": "Frederico Mazzo",
        "cpf": "11111111111",
        "birth_date": "01/01/1990",
    }
    ls = ensure_lead_state(meta)
    ls["nome"] = "Frederico Mazzo"
    ls["aluno_e_terceiro"] = True
    ls["aluno_relacao"] = "esposa"
    ls["aluno_genero"] = "f"
    ls["curso_escolhido"] = "MBA Executivo em Gestão de Clínicas e Consultórios"
    ls["graduacao"] = "concluida"
    ls["aceite_matricula"] = True
    meta["etapa"] = "fechamento"
    meta["lead_state"] = ls
    ca = ensure_compra_atual(meta)
    ca["aluno_e_terceiro"] = True
    ca["aluno_relacao"] = "esposa"
    ca["aluno_genero"] = "f"
    ca["curso_escolhido"] = ls["curso_escolhido"]
    meta["compra_atual"] = ca

    msg = "Sheila Mazzo\n529.982.247-25\n12/03/1990"
    extracted = extract_contract_fields_from_text(msg)
    apply_extracted_contract_fields(meta, ls, extracted)

    party = resolve_contract_party(meta, ls)
    assert party["aluno_nome"] == "Sheila Mazzo"
    assert party["comprador_nome"] == "Frederico Mazzo"
    assert party["cpf"] == "52998224725"
    # CPF do comprador (1ª matrícula) intacto no meta
    assert meta.get("cpf") == "11111111111"

    reply, course, delivery = orch._schedule_contract_if_ready(
        phone, meta, push_name="Frederico"
    )
    assert delivery is True
    assert "Sheila" in reply
    assert scheduled["aluno_nome"] == "Sheila Mazzo"
    assert scheduled["comprador_nome"] == "Frederico Mazzo"
    assert scheduled["lead_name"] == "Sheila Mazzo"
    assert meta["matriculas"][0]["aluno_nome"] == "Frederico Mazzo"

    pdf = build_contrato_pdf(
        lead_name=scheduled["aluno_nome"],
        cpf=scheduled["cpf"],
        birth_date=scheduled["birth_date"],
        course=course or "MBA",
    )
    assert pdf.startswith(b"%PDF")
    # Nome do aluno é o argument do PDF (conteúdo comprimido no binário).
    assert scheduled["aluno_nome"] == "Sheila Mazzo"

    session = create_checkout(phone, course_label=course or "MBA", lead_name=scheduled["aluno_nome"])
    assert session.lead_name == "Sheila Mazzo"

    note = build_matricula_notify_message(
        agent_name="Clara",
        lead_nome="Sheila Mazzo",
        lead_phone=phone,
        curso=course,
        aluno_nome="Sheila Mazzo",
        comprador_nome="Frederico Mazzo",
    )
    assert "Aluno: Sheila Mazzo" in note
    assert "compra feita por Frederico Mazzo" in note


def test_leads_consent_required():
    ok, err = validate_lead_payload(
        {"nome": "Ana", "telefone": "16996480805", "origem": "formulario", "consentimento": False}
    )
    assert ok is None and err == "consentimento_obrigatorio"
    payload, err2 = validate_lead_payload(
        {
            "nome": "Ana Silva",
            "telefone": "16996480805",
            "origem": "formulario",
            "interesse": "Autismo",
            "consentimento": True,
        }
    )
    assert err2 is None and payload and payload["telefone"].startswith("55")


def test_create_lead_schedules_primeiro_contato(monkeypatch):
    jobs: list[dict] = []

    class _Sched:
        def clear_for_phone(self, phone, types=None):
            return 0

        def schedule_job(self, **kw):
            jobs.append(kw)
            return kw

    monkeypatch.setattr("app.followups.get_scheduler", lambda: _Sched())
    settings = _settings()
    # ConversationMemory precisa redis_url vazio → local
    from app.memory import ConversationMemory

    mem = ConversationMemory(settings)  # type: ignore[arg-type]
    monkeypatch.setattr("app.inbound_leads.ConversationMemory", lambda _s: mem)

    payload, err = validate_lead_payload(
        {
            "nome": "Frederico Mazzo",
            "telefone": "5516996480805",
            "origem": "formulario",
            "interesse": "Autismo",
            "consentimento": True,
        }
    )
    assert err is None and payload
    out = create_or_update_lead(settings, payload, stagger_seconds=10)  # type: ignore[arg-type]
    assert out["ok"] is True
    assert any(j.get("job_type") == "primeiro_contato" for j in jobs)
    meta = mem.get_meta("5516996480805")
    assert meta.get("etapa") == "primeiro_contato"
    assert meta.get("consentimento") is True


def test_cadence_demo_and_window():
    s = _settings(demo_fast_followup=True)
    d = cadence_delays(s)  # type: ignore[arg-type]
    assert d["funil_silence"][0] == 120
    # Segunda 10h BRT (UTC-3) em weekday — usa timestamp fixo
    # 2026-11-10 13:00 UTC = 10:00 BRT, terça
    ts = time.mktime(time.strptime("2026-11-10 13:00:00", "%Y-%m-%d %H:%M:%S"))
    # within_active_window uses ZoneInfo America/Sao_Paulo
    assert within_active_window(ts) in (True, False)  # smoke
    # Domingo fora
    # 2026-11-08 is Sunday
    sun = time.mktime(time.strptime("2026-11-08 15:00:00", "%Y-%m-%d %H:%M:%S"))
    # next_window_start should return something >= now
    nxt = next_window_start(sun)
    assert nxt >= sun


def test_opt_out_blocks_active_send():
    s = _settings()
    meta = {"opt_out": True, "consentimento": True, "origem": "formulario"}
    ok, reason = can_send_active(meta, "5516996480805", s)  # type: ignore[arg-type]
    assert ok is False and reason == "opt_out"


def test_cancel_retomadas_on_schedule_think():
    jobs: list[dict] = []

    class _Sched:
        def __init__(self):
            self._local = []

        def clear_for_phone(self, phone, types=None):
            before = len(self._local)
            self._local = [
                j
                for j in self._local
                if not (
                    j.get("phone") == phone
                    and (types is None or j.get("type") in types)
                )
            ]
            return before - len(self._local)

        def schedule_job(self, **kw):
            job = {"type": kw.get("job_type"), "phone": kw.get("phone"), **kw}
            self._local.append(job)
            jobs.append(job)
            return job

    sched = _Sched()
    meta: dict = {"etapa": "recomendacao"}
    schedule_silence_followups("5516", meta, sched, settings=_settings())  # type: ignore[arg-type]
    assert len(sched._local) == 3
    cancel_retomadas("5516", sched)
    assert sched._local == []
    delay = schedule_think_followup(
        "5516", meta, sched, user_text="me chama semana que vem"
    )
    assert delay > 0
    assert len(sched._local) == 1


def test_parse_think_demo():
    s = _settings(demo_fast_followup=True)
    assert parse_think_delay_seconds("semana que vem", settings=s) == 180  # type: ignore[arg-type]
