"""Monta Orchestrator isolado e executa um cenário."""

from __future__ import annotations

import re
from typing import Any

from app.config import Settings, get_settings
from app.orchestrator import Orchestrator

from scripts.sim.auto_judge import judge_agent_reply, load_catalog, looks_like_farewell
from scripts.sim.lead import LEAD_TEMPERATURE, generate_lead_message
from scripts.sim.llm_judge import JUDGE_TEMPERATURE, judge_conversation
from scripts.sim.mocks import MockEvolution, MockScheduler


def patch_scheduler(mock: MockScheduler) -> None:
    import app.followups as followups
    import app.orchestrator as orch_mod

    followups.get_scheduler = lambda: mock  # type: ignore[assignment]
    orch_mod.get_scheduler = lambda: mock  # type: ignore[assignment]
    followups._scheduler = mock  # type: ignore[attr-defined]


async def _noop_preamble(*_a: Any, **_k: Any) -> None:
    return None


def build_orchestrator(settings: Settings, evo: MockEvolution) -> Orchestrator:
    orch = Orchestrator(settings)
    orch.evo = evo  # type: ignore[assignment]
    orch._human_preamble = _noop_preamble  # type: ignore[method-assign]
    return orch


def _is_picado(estilo: str) -> bool:
    return "picad" in (estilo or "").casefold()


def _outcome_from_state(
    *,
    scheduled: bool,
    reply: str,
    meta: dict,
    lead_text: str,
    persona: dict,
) -> str | None:
    """Retorna outcome se deve encerrar, senão None."""
    if scheduled:
        return "fechou_followup"
    if "http" in (reply or "").casefold() and "checkout" in (reply or "").casefold():
        return "fechou_checkout"
    if re.search(r"https?://\S*checkout", reply or "", re.I):
        return "fechou_checkout"
    low = (lead_text or "").casefold()
    desiste_hints = (
        "deixa pra lá",
        "deixa pra la",
        "não quero mais",
        "nao quero mais",
        "pode esquecer",
        "desisto",
        "para por aqui",
    )
    if any(h in low for h in desiste_hints):
        return "desistiu"
    etapa = meta.get("etapa")
    if etapa == "aluno_atual" and "boleto" in (persona.get("objecao") or ""):
        # deixa alguns turnos; se agente já orientou atendimento, pode continuar até max
        pass
    if etapa == "matriculado":
        return "fechou_matriculado"
    return None


async def run_persona(
    *,
    persona: dict[str, Any],
    settings: Settings,
    lead_model: str,
    judge_model: str,
    agent_model: str,
    max_turns: int = 16,
) -> dict[str, Any]:
    phone = f"sim:{persona['id']}"
    evo = MockEvolution()
    sched = MockScheduler()
    patch_scheduler(sched)
    orch = build_orchestrator(settings, evo)
    catalog = load_catalog()

    history: list[dict[str, Any]] = []
    violations: list[dict[str, Any]] = []
    outcome = "max_turnos"
    jobs_mark = 0
    farewell_streak = 0

    # limpa memória residual do phone
    orch.memory.clear(phone)

    for turn in range(1, max_turns + 1):
        picado = _is_picado(str(persona.get("estilo") or "")) and turn > 1
        if turn == 1 and persona.get("primeira_mensagem"):
            lead_raw: str | list[str] = str(persona["primeira_mensagem"])
        else:
            lead_raw = await generate_lead_message(
                settings,
                model=lead_model,
                persona=persona,
                history=[{"role": h["role"], "text": h["text"]} for h in history],
                picado=picado,
            )

        if isinstance(lead_raw, list):
            lead_text = "\n".join(lead_raw)
            lead_display = " | ".join(lead_raw)
        else:
            lead_text = lead_raw
            lead_display = lead_raw

        history.append({"role": "lead", "turno": turn, "text": lead_display})

        if looks_like_farewell(lead_text):
            farewell_streak += 1
        else:
            farewell_streak = 0

        meta_before = orch.memory.get_meta(phone)
        ls_before = meta_before.get("lead_state") or {}
        aceite_before = bool(ls_before.get("aceite_matricula"))

        reply = await orch.handle_inbound(
            phone,
            lead_text,
            push_name=str(persona.get("nome") or ""),
        )
        # prefer what was actually "sent"
        sent = evo.drain_texts()
        agent_text = sent or (reply or "")

        new_jobs = sched.jobs[jobs_mark:]
        jobs_mark = len(sched.jobs)
        action_executed = bool(new_jobs) or bool(
            re.search(r"https?://\S*checkout", agent_text, re.I)
        )

        history.append({"role": "agent", "turno": turn, "text": agent_text})

        turn_violations = judge_agent_reply(
            agent_text,
            turno=turn,
            aceite_matricula=aceite_before,
            action_executed=action_executed,
            catalog=catalog,
            lead_text=lead_text,
        )
        violations.extend(turn_violations)

        meta = orch.memory.get_meta(phone)
        if farewell_streak >= 2:
            outcome = "lead_encerrou"
            break
        stop = _outcome_from_state(
            scheduled=bool(new_jobs),
            reply=agent_text,
            meta=meta,
            lead_text=lead_text,
            persona=persona,
        )
        if stop:
            outcome = stop
            break

    meta = orch.memory.get_meta(phone)
    judge = await judge_conversation(
        settings,
        model=judge_model,
        persona=persona,
        history=[{"role": h["role"], "text": h["text"]} for h in history],
        violations=violations,
        outcome_hint=f"{outcome}; etapa={meta.get('etapa')}",
    )

    orch.memory.clear(phone)

    return {
        "persona_id": persona["id"],
        "nome": persona.get("nome"),
        "outcome": outcome,
        "etapa_final": meta.get("etapa"),
        "history": history,
        "violations": violations,
        "judge": judge,
        "scheduler_log": list(sched.log),
        "models": {
            "agent": agent_model,
            "lead": lead_model,
            "judge": judge_model,
            "lead_temperature": LEAD_TEMPERATURE,
            "judge_temperature": JUDGE_TEMPERATURE,
        },
    }
