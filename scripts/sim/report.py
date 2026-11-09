"""Gera reports/sim-*.md e .json."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any


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
    lines.append("| Cenário | Veredito | Escuta | Qualif | Objeção | Nat | Condução | Média | Violações |")
    lines.append("|---|---|---:|---:|---:|---:|---:|---:|---:|")

    avgs = {"escuta": [], "qualificacao": [], "objecao": [], "naturalidade": [], "conducao": []}
    all_violations: list[tuple[str, dict]] = []

    for r in results:
        j = r.get("judge") or {}
        scores = [j.get(k, 0) for k in avgs]
        mean = sum(scores) / len(scores) if scores else 0
        for k in avgs:
            if k in j:
                avgs[k].append(j[k])
        n_v = len(r.get("violations") or [])
        lines.append(
            f"| {r.get('persona_id')} | {j.get('veredito', '-')} | "
            f"{j.get('escuta', '-')} | {j.get('qualificacao', '-')} | {j.get('objecao', '-')} | "
            f"{j.get('naturalidade', '-')} | {j.get('conducao', '-')} | {mean:.1f} | {n_v} |"
        )
        for v in r.get("violations") or []:
            all_violations.append((r.get("persona_id", ""), v))

    lines.append("")
    lines.append("## Médias gerais")
    lines.append("")
    for k, vals in avgs.items():
        if vals:
            lines.append(f"- **{k}**: {sum(vals) / len(vals):.2f}")
    lines.append("")

    # top 5 piores trechos
    lines.append("## Top 5 piores trechos (violações)")
    lines.append("")
    ranked = sorted(all_violations, key=lambda x: x[1].get("turno", 0), reverse=True)[:5]
    if not ranked:
        # prefer severity by regra
        ranked = all_violations[:5]
    for i, (pid, v) in enumerate(ranked[:5], 1):
        lines.append(f"### {i}. `{pid}` turno {v.get('turno')} — {v.get('regra')}")
        lines.append(f"> {v.get('trecho')}")
        # contexto
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
