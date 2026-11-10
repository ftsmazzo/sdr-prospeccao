"""Inbox: transferência humano/IA e pausa da Clara."""

from __future__ import annotations

from app.inbox import get_conversation, return_to_ai, transfer_to_human
from app.memory import ConversationMemory


class _Settings:
    redis_url = ""
    memory_ttl_seconds = 3600
    memory_max_messages = 30
    agent_name = "Clara"


def test_transfer_and_return_to_ai(monkeypatch):
    settings = _Settings()
    mem = ConversationMemory(settings)
    phone = "5516996480805"
    mem.clear(phone)
    mem.set_meta(
        phone,
        {
            "etapa": "objecao",
            "lead_state": {"nome": "Frederico", "graduacao": "concluida"},
        },
    )
    mem.append(phone, "user", "Oi")
    mem.append(phone, "assistant", "Olá!")

    # Evita scheduler Redis real
    class FakeSched:
        def clear_for_phone(self, *a, **k):
            return 0

    monkeypatch.setattr("app.followups.get_scheduler", lambda: FakeSched())

    r = transfer_to_human(settings, phone)
    assert r["modo"] == "humano"
    meta = mem.get_meta(phone)
    assert meta.get("ai_paused") is True
    assert meta.get("etapa") == "handoff_humano"

    conv = get_conversation(settings, phone)
    assert conv is not None
    assert conv["modo"] == "humano"
    assert len(conv["messages"]) == 2

    r2 = return_to_ai(settings, phone)
    assert r2["modo"] == "ia"
    meta2 = mem.get_meta(phone)
    assert meta2.get("ai_paused") is False
    assert meta2.get("etapa") == "objecao"
