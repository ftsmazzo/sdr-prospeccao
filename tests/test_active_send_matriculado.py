"""Retomadas não devem sair após matrícula."""

from __future__ import annotations

from types import SimpleNamespace

from app.active_send import can_send_active
from app.outbound_cadence import schedule_contract_followups


def test_can_send_blocks_matriculado():
    settings = SimpleNamespace(handoff_notify_numbers="")
    meta = {"etapa": "matriculado", "consentimento": True}
    ok, reason = can_send_active(meta, "5516996480805", settings)
    assert ok is False
    assert "matriculado" in reason


def test_schedule_contract_skipped_when_matriculado():
    class FakeSched:
        def __init__(self) -> None:
            self.jobs: list[dict] = []

        def clear_for_phone(self, phone, types=None):
            n = len(self.jobs)
            self.jobs.clear()
            return n

        def schedule_job(self, **kwargs):
            self.jobs.append(kwargs)

    sched = FakeSched()
    meta = {"etapa": "matriculado"}
    schedule_contract_followups("5516996480805", meta, sched)
    assert sched.jobs == []
    assert meta.get("proxima_retomada_at") is None
