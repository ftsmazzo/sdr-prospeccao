"""Gera reports/sim-*.md e .json."""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any


def _short(text: str, n: int = 80) -> str:
    t = re.sub(r"\s+", " ", (text or "").strip())
    return t if len(t) <= n else t[: n - 1] + "…"


def write_reports(
    results: list[dict[str, Any]],
    *,
    models: dict[str, str],
    out_dir: Path,
) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    md_path = out_dir / f"sim-{stamp}.md"
    json_path = out_dir / f"sim-{stamp}.json"

    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "models": models,
        "results": results,
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    lines: list[str] = []
    lines.append(f"# Simulação de leads — {stamp}")
    lines.append("")
    lines.append("## Modelos")
    lines.append(f"- Agente: `{models.get('agent')}`")
    lines.append(f"- Lead: `{models.get('lead')}` (temp {models.get('lead_temperature')})")
    lines.append(f"- Juiz: `{models.get('judge')}` (temp {models.get('judge_temperature')})")
    lines.append("")
    lines.append("## Tabela por cenário")
    lines.append("")
    lines.append(
        "| Cenário | Veredito | Escuta | Qualif | Objeção | Nat | Condução | Verac. | Média | "
        "Violações | Regen | Stock | Stock×2 |"
    )
    lines.append("|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")

    avgs = {
        "escuta": [],
        "qualificacao": [],
        "objecao": [],
        "naturalidade": [],
        "conducao": [],
        "veracidade": [],
    }
    all_violations: list[tuple[str, dict]] = []

    # Custo estimado (OpenRouter público aproximado, USD / 1M tokens).
    # Heurística: ~2.5k prompt + 0.4k completion por turno agente; lead similar; juiz 1x.
    _PRICE = {
        "openai/gpt-4.1-mini": {"in": 0.40, "out": 1.60},
        "openai/gpt-4.1": {"in": 2.00, "out": 8.00},
        "anthropic/claude-sonnet-5": {"in": 2.00, "out": 10.00},
        "anthropic/claude-sonnet-4": {"in": 3.00, "out": 15.00},
        "anthropic/claude-3.5-sonnet": {"in": 3.00, "out": 15.00},
    }
    agent_m = str(models.get("agent") or "")
    lead_m = str(models.get("lead") or "")
    judge_m = str(models.get("judge") or "")
    cost_rows: list[tuple[str, float, int]] = []

    def _usd(model: str, tin: float, tout: float) -> float:
        p = _PRICE.get(model) or {"in": 1.0, "out": 4.0}
        return (tin * p["in"] + tout * p["out"]) / 1_000_000

    for r in results:
        j = r.get("judge") or {}
        if j.get("veredito") == "erro_avaliacao":
            mean_s = "-"
            for k in avgs:
                pass
            scores_disp = ["-"] * 6
            mean = 0.0
        else:
            scores_disp = []
            nums: list[float] = []
            for k in avgs:
                v = j.get(k)
                if isinstance(v, (int, float)):
                    avgs[k].append(float(v))
                    nums.append(float(v))
                    scores_disp.append(str(int(v)))
                else:
                    scores_disp.append("-")
            mean = sum(nums) / len(nums) if nums else 0.0
            mean_s = f"{mean:.1f}"
        n_v = len(r.get("violations") or [])
        diag = r.get("diagnostics") or {}
        n_turns = max(
            (h.get("turno") or 0 for h in (r.get("history") or [])),
            default=0,
        )
        usd = (
            _usd(agent_m, n_turns * 2500, n_turns * 400)
            + _usd(lead_m, n_turns * 1800, n_turns * 250)
            + _usd(judge_m, 3500, 600)
        )
        cost_rows.append((str(r.get("persona_id")), usd, int(n_turns)))
        lines.append(
            f"| {r.get('persona_id')} | {j.get('veredito', '-')} | "
            f"{scores_disp[0]} | {scores_disp[1]} | {scores_disp[2]} | "
            f"{scores_disp[3]} | {scores_disp[4]} | {scores_disp[5]} | "
            f"{mean_s} | {n_v} | "
            f"{diag.get('regen_count', 0)} | {diag.get('stock_count', 0)} | "
            f"{diag.get('stock_repeat_count', 0)} |"
        )
        for v in r.get("violations") or []:
            all_violations.append((r.get("persona_id", ""), v))

    lines.append("")
    lines.append("## Médias gerais")
    lines.append("")
    for k, vals in avgs.items():
        if vals:
            lines.append(f"- **{k}**: {sum(vals) / len(vals):.2f}")
    if cost_rows:
        avg_cost = sum(c for _, c, _ in cost_rows) / len(cost_rows)
        lines.append(
            f"- **custo estimado / conversa**: US$ {avg_cost:.4f} "
            f"(agente `{agent_m}`)"
        )
        latencies = [
            float((r.get("diagnostics") or {}).get("avg_latency_ms") or 0)
            for r in results
            if (r.get("diagnostics") or {}).get("avg_latency_ms")
        ]
        if latencies:
            lines.append(
                f"- **latência média / turno (agente)**: "
                f"{sum(latencies) / len(latencies):.0f} ms"
            )
    lines.append("")

    lines.append("## Justificativas de veracidade")
    lines.append("")
    for r in results:
        j = r.get("judge") or {}
        just = (j.get("justificativas") or {}).get("veracidade") or ""
        if j.get("veredito") == "erro_avaliacao":
            lines.append(f"### `{r.get('persona_id')}` — erro_avaliacao")
            lines.append(f"> {just or '_falha de leitura do juiz_'}")
            lines.append("")
            continue
        score = j.get("veracidade")
        if score is None:
            continue
        try:
            score_i = int(score)
        except (TypeError, ValueError):
            score_i = 0
        mark = " [baixa]" if score_i < 4 else ""
        lines.append(f"### `{r.get('persona_id')}` — veracidade={score}{mark}")
        lines.append(f"> {just or '_sem justificativa_'}")
        lines.append("")

    lines.append("## Diagnóstico regen / stock")
    lines.append("")
    for r in results:
        diag = r.get("diagnostics") or {}
        lines.append(
            f"### `{r.get('persona_id')}` — "
            f"regen={diag.get('regen_count', 0)} · "
            f"stock={diag.get('stock_count', 0)} · "
            f"stock×2={diag.get('stock_repeat_count', 0)}"
        )
        lines.append("")
        regens = diag.get("regens") or []
        if regens:
            lines.append("**Regenerações**")
            for ev in regens:
                lines.append(f"- t{ev.get('turno')}: `{ev.get('motivo')}`")
            lines.append("")
        stocks = diag.get("stocks") or []
        if stocks:
            lines.append("**Frases prontas (stock)**")
            for ev in stocks:
                lines.append(
                    f"- t{ev.get('turno')} (`{ev.get('motivo')}`): "
                    f"{_short(str(ev.get('frase') or ''))}"
                )
            lines.append("")
        repeats = diag.get("stock_repeats") or []
        if repeats:
            lines.append("**Stock repetido em turnos seguidos**")
            for ev in repeats:
                lines.append(
                    f"- t{ev.get('turno_anterior')}→t{ev.get('turno')}: "
                    f"{_short(str(ev.get('frase') or ''))}"
                )
            lines.append("")
        if not regens and not stocks:
            lines.append("_Sem regen nem stock neste cenário._")
            lines.append("")

    lines.append("## Top 5 piores trechos (violações)")
    lines.append("")
    ranked = sorted(all_violations, key=lambda x: x[1].get("turno", 0), reverse=True)[:5]
    if not ranked:
        ranked = all_violations[:5]
    if not ranked:
        lines.append("_Nenhuma violação automática._")
        lines.append("")
    for i, (pid, v) in enumerate(ranked[:5], 1):
        lines.append(f"### {i}. `{pid}` turno {v.get('turno')} — {v.get('regra')}")
        lines.append(f"> {v.get('trecho')}")
        hist = next((r.get("history") or [] for r in results if r.get("persona_id") == pid), [])
        t = int(v.get("turno") or 0)
        ctx = [h for h in hist if abs(h.get("turno", 0) - t) <= 1]
        if ctx:
            lines.append("")
            lines.append("```")
            for h in ctx:
                lines.append(f"[{h.get('turno')}] {h.get('role')}: {h.get('text')}")
            lines.append("```")
        lines.append("")

    lines.append("## Conversas completas")
    lines.append("")
    for r in results:
        lines.append(f"### {r.get('persona_id')} — {r.get('outcome')}")
        lines.append("")
        for h in r.get("history") or []:
            lines.append(f"**{h.get('role')}** (t{h.get('turno')}): {h.get('text')}")
            lines.append("")
        if r.get("scheduler_log"):
            lines.append("_Ações simuladas:_")
            for s in r["scheduler_log"]:
                lines.append(f"- {s}")
            lines.append("")

    md_path.write_text("\n".join(lines), encoding="utf-8")
    return md_path, json_path
