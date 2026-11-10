"""
Simulação de leads vs Orchestrator.

Uso:
  python -m scripts.sim.run --persona enfermeira_estetica_tempo
  python -m scripts.sim.run --all --yes
  python -m scripts.sim.run --smoke --yes
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

# --- Isolamento ANTES de qualquer import de app/ ---
from scripts.sim.isolate import apply_sim_env, assert_sim_settings

apply_sim_env()

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from app.config import get_settings  # noqa: E402

get_settings.cache_clear()
_settings = get_settings()
assert_sim_settings(_settings)

from scripts.sim.harness import run_persona  # noqa: E402
from scripts.sim.lead import LEAD_TEMPERATURE  # noqa: E402
from scripts.sim.llm_judge import JUDGE_TEMPERATURE  # noqa: E402
from scripts.sim.report import write_reports  # noqa: E402

# Heurística de custo (USD / 1M tokens) — alinhada ao report.
_PRICE = {
    "openai/gpt-4.1-mini": {"in": 0.40, "out": 1.60},
    "openai/gpt-4.1": {"in": 2.00, "out": 8.00},
    "anthropic/claude-sonnet-5": {"in": 2.00, "out": 10.00},
}


def _usd(model: str, tin: float, tout: float) -> float:
    p = _PRICE.get(model) or {"in": 1.0, "out": 4.0}
    return (tin * p["in"] + tout * p["out"]) / 1_000_000


def _estimate_scenario_usd(agent: str, lead: str, judge: str, turns: int) -> float:
    return (
        _usd(agent, turns * 2500, turns * 400)
        + _usd(lead, turns * 1800, turns * 250)
        + _usd(judge, 3500, 600)
    )


def _load_personas() -> list[dict]:
    path = Path(__file__).with_name("personas.json")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise SystemExit("personas.json inválido")
    return data


def _estimate_and_confirm(n_scenarios: int, *, yes: bool, models: dict, budget: float) -> None:
    max_turns = 16
    calls = n_scenarios * (max_turns * 2 + 1)
    print("=== Simulação Edu SDR ===")
    print(f"Cenários: {n_scenarios}")
    print(f"Estimativa máx. chamadas LLM: ~{calls} (16 turnos × 2 + 1 juiz por cenário)")
    print(f"Modelo agente: {models['agent']}")
    print(f"Modelo lead:   {models['lead']} (temp {LEAD_TEMPERATURE})")
    print(f"Modelo juiz:   {models['judge']} (temp {JUDGE_TEMPERATURE})")
    print(f"Budget: US$ {budget:.2f}")
    print("Isolation: REDIS vazio, Evolution http://sim.invalid, TTS off")
    if yes:
        print("--yes: seguindo sem confirmação")
        return
    ans = input("Confirma rodar? [Enter=sim / n=não] ").strip().casefold()
    if ans in ("n", "nao", "não", "no"):
        raise SystemExit("Cancelado.")


async def _amain(args: argparse.Namespace) -> int:
    settings = get_settings()
    assert_sim_settings(settings)

    agent_model = os.environ.get("SIM_AGENT_MODEL", settings.openrouter_model)
    lead_model = os.environ.get("SIM_LEAD_MODEL", "openai/gpt-4.1-mini")
    judge_model = os.environ.get("SIM_JUDGE_MODEL", "openai/gpt-4.1")
    models = {
        "agent": agent_model,
        "lead": lead_model,
        "judge": judge_model,
        "lead_temperature": LEAD_TEMPERATURE,
        "judge_temperature": JUDGE_TEMPERATURE,
    }
    budget = float(args.budget)

    all_personas = _load_personas()

    # --smoke: 1 cenário, 3 turnos, valida JSON/tool
    if args.smoke:
        smoke_p = next(
            (p for p in all_personas if p.get("id") == "fechamento_rapido"),
            all_personas[0],
        )
        print("=== SMOKE (1 cenário, 3 turnos) ===")
        smoke = await run_persona(
            persona=smoke_p,
            settings=settings,
            lead_model=lead_model,
            judge_model=judge_model,
            agent_model=agent_model,
            max_turns=3,
            abort_on_json_fallback=True,
            max_json_fallbacks=3,
        )
        diag = smoke.get("diagnostics") or {}
        if diag.get("json_fallback_aborted") or smoke.get("outcome") == "json_fallback_abort":
            print("SMOKE FALHOU: fallbacks JSON/tool demais")
            return 2
        print(f"SMOKE OK persona={smoke_p.get('id')} outcome={smoke.get('outcome')}")
        if args.smoke_only or (not args.all and not args.persona):
            return 0

    # --all / --persona: smoke automático antes (exceto se já rodou --smoke)
    run_full = bool(args.all or args.persona)
    if run_full and not args.smoke and not args.skip_smoke:
        print("\n=== Smoke automático antes da rodada ===")
        smoke_p = next(
            (p for p in all_personas if p.get("id") == "fechamento_rapido"),
            all_personas[0],
        )
        smoke = await run_persona(
            persona=smoke_p,
            settings=settings,
            lead_model=lead_model,
            judge_model=judge_model,
            agent_model=agent_model,
            max_turns=3,
            abort_on_json_fallback=True,
            max_json_fallbacks=3,
        )
        diag = smoke.get("diagnostics") or {}
        if diag.get("json_fallback_aborted") or smoke.get("outcome") == "json_fallback_abort":
            print("ABORT: smoke falhou — não inicia rodada maior")
            return 2
        print("Smoke OK — seguindo\n")

    personas = list(all_personas)
    if args.persona:
        wanted: list[str] = []
        for chunk in args.persona:
            wanted.extend(x.strip() for x in str(chunk).split(",") if x.strip())
        wanted_set = set(wanted)
        personas = [p for p in personas if p.get("id") in wanted_set]
        missing = wanted_set - {p.get("id") for p in personas}
        if missing:
            raise SystemExit(f"Persona(s) não encontrada(s): {', '.join(sorted(missing))}")
        order = {pid: i for i, pid in enumerate(wanted)}
        personas.sort(key=lambda p: order.get(str(p.get("id")), 999))
    elif not args.all:
        if args.smoke:
            return 0
        raise SystemExit("use --persona ID, --all ou --smoke")

    _estimate_and_confirm(len(personas), yes=args.yes, models=models, budget=budget)

    results = []
    spent = 0.0
    for p in personas:
        est = _estimate_scenario_usd(agent_model, lead_model, judge_model, 16)
        if spent + est > budget and results:
            print(f"\nBUDGET: parando (gasto est. US$ {spent:.4f} + próximo ~{est:.4f} > {budget:.2f})")
            break
        print(f"\n--- Rodando {p['id']} ---")
        result = await run_persona(
            persona=p,
            settings=settings,
            lead_model=lead_model,
            judge_model=judge_model,
            agent_model=agent_model,
            max_turns=16,
            abort_on_json_fallback=True,
            max_json_fallbacks=3,
        )
        results.append(result)
        n_turns = max((h.get("turno") or 0 for h in (result.get("history") or [])), default=0)
        spent += _estimate_scenario_usd(agent_model, lead_model, judge_model, int(n_turns) or 1)
        j = result.get("judge") or {}
        print(
            f"OK {p['id']}: veredito={j.get('veredito')} "
            f"violations={len(result.get('violations') or [])} "
            f"outcome={result.get('outcome')} "
            f"spent~US${spent:.4f}"
        )
        if result.get("outcome") == "json_fallback_abort":
            print("Cenário abortado por 3 fallbacks JSON seguidos")

    out_dir = _ROOT / "reports"
    md_path, json_path = write_reports(results, models=models, out_dir=out_dir)
    print(f"\nRelatório: {md_path}")
    print(f"JSON:      {json_path}")
    try:
        print("\n" + md_path.read_text(encoding="utf-8"))
    except UnicodeEncodeError:
        print("\n(relatório salvo; stdout omitido por encoding do console)")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Simulação de leads Edu SDR")
    parser.add_argument(
        "--persona",
        action="append",
        help="id da persona (repetível ou lista separada por vírgula)",
    )
    parser.add_argument("--all", action="store_true", help="roda todas as personas")
    parser.add_argument("--yes", action="store_true", help="pula confirmação de custo")
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="1 cenário, 3 turnos; valida JSON/tool e aborta se falhar",
    )
    parser.add_argument(
        "--smoke-only",
        action="store_true",
        help="com --smoke, não continua para --all/--persona",
    )
    parser.add_argument(
        "--skip-smoke",
        action="store_true",
        help="não roda smoke automático antes de --all/--persona",
    )
    parser.add_argument(
        "--budget",
        type=float,
        default=1.0,
        help="orçamento estimado USD (padrão 1.00); para a rodada ao estourar",
    )
    args = parser.parse_args()
    if not args.persona and not args.all and not args.smoke:
        parser.error("use --persona ID, --all ou --smoke")
    raise SystemExit(asyncio.run(_amain(args)))


if __name__ == "__main__":
    main()
