"""
Simulação de leads vs Orchestrator.

Uso:
  python -m scripts.sim.run --persona enfermeira_estetica_tempo
  python -m scripts.sim.run --all --yes
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

# garanta raiz do repo no path
_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# agora sim: app/
from app.config import get_settings  # noqa: E402

get_settings.cache_clear()
_settings = get_settings()
assert_sim_settings(_settings)

from scripts.sim.harness import run_persona  # noqa: E402
from scripts.sim.lead import LEAD_TEMPERATURE  # noqa: E402
from scripts.sim.llm_judge import JUDGE_TEMPERATURE  # noqa: E402
from scripts.sim.report import write_reports  # noqa: E402


def _load_personas() -> list[dict]:
    # JSON (personas.yaml espelhado) — evita PyYAML no Windows/Py3.14
    path = Path(__file__).with_name("personas.json")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise SystemExit("personas.json inválido")
    return data


def _estimate_and_confirm(n_scenarios: int, *, yes: bool, models: dict) -> None:
    max_turns = 16
    # por cenário: até 16 lead + 16 agente + 1 juiz
    calls = n_scenarios * (max_turns * 2 + 1)
    print("=== Simulação Edu SDR ===")
    print(f"Cenários: {n_scenarios}")
    print(f"Estimativa máx. chamadas LLM: ~{calls} (16 turnos × 2 + 1 juiz por cenário)")
    print(f"Modelo agente: {models['agent']}")
    print(f"Modelo lead:   {models['lead']} (temp {LEAD_TEMPERATURE})")
    print(f"Modelo juiz:   {models['judge']} (temp {JUDGE_TEMPERATURE})")
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

    personas = _load_personas()
    if args.persona:
        wanted: list[str] = []
        for chunk in args.persona:
            wanted.extend(x.strip() for x in str(chunk).split(",") if x.strip())
        wanted_set = set(wanted)
        personas = [p for p in personas if p.get("id") in wanted_set]
        missing = wanted_set - {p.get("id") for p in personas}
        if missing:
            raise SystemExit(f"Persona(s) não encontrada(s): {', '.join(sorted(missing))}")
        # preserva ordem pedida
        order = {pid: i for i, pid in enumerate(wanted)}
        personas.sort(key=lambda p: order.get(str(p.get("id")), 999))

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

    _estimate_and_confirm(len(personas), yes=args.yes, models=models)

    results = []
    for p in personas:
        print(f"\n--- Rodando {p['id']} ---")
        result = await run_persona(
            persona=p,
            settings=settings,
            lead_model=lead_model,
            judge_model=judge_model,
            agent_model=agent_model,
            max_turns=16,
        )
        results.append(result)
        j = result.get("judge") or {}
        print(
            f"OK {p['id']}: veredito={j.get('veredito')} "
            f"violations={len(result.get('violations') or [])} "
            f"outcome={result.get('outcome')}"
        )

    out_dir = _ROOT / "reports"
    md_path, json_path = write_reports(results, models=models, out_dir=out_dir)
    print(f"\nRelatório: {md_path}")
    print(f"JSON:      {json_path}")
    # Evita UnicodeEncodeError no console Windows (cp1252).
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
    args = parser.parse_args()
    if not args.persona and not args.all:
        parser.error("use --persona ID ou --all")
    raise SystemExit(asyncio.run(_amain(args)))


if __name__ == "__main__":
    main()
