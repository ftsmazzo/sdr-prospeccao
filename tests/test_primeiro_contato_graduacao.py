"""Primeiro contato respeita graduação já informada no formulário."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from app.outbound_cadence import compose_active_message


def _run(meta: dict) -> str:
    settings = SimpleNamespace(
        openrouter_api_key="",
        agent_name="Clara",
        demo_fast_followup=True,
    )
    return asyncio.run(
        compose_active_message(
            settings,
            "5516996480805",
            meta,
            {"type": "primeiro_contato", "trigger": "primeiro_contato", "step": 0},
        )
    )


def test_primeiro_contato_concluida_nao_repergunta():
    text = _run(
        {
            "etapa": "primeiro_contato",
            "origem": "formulário",
            "interesse": "Inteligência Artificial para Negócios",
            "lead_state": {
                "nome": "Frederico",
                "graduacao": "concluida",
                "area_interesse": "Inteligência Artificial para Negócios",
            },
        }
    )
    low = text.casefold()
    # Pode reconhecer ("vi que você já concluiu"), mas não perguntar de novo.
    assert "?" in text
    assert "objetivo" in low or "especialização" in low or "especializacao" in low
    assert "você já concluiu a graduação?" not in low
    assert "já concluiu a graduação?" not in low


def test_primeiro_contato_cursando():
    text = _run(
        {
            "etapa": "primeiro_contato",
            "origem": "formulário",
            "interesse": "TEA",
            "lead_state": {"nome": "Ana", "graduacao": "cursando"},
        }
    )
    low = text.casefold()
    assert "diploma" in low or "declaração" in low or "declaracao" in low


def test_primeiro_contato_sem_graduacao_pergunta():
    text = _run(
        {
            "etapa": "primeiro_contato",
            "origem": "formulário",
            "interesse": "Gestão",
            "lead_state": {"nome": "João"},
        }
    )
    assert "graduação" in text.casefold() or "graduacao" in text.casefold()
