"""Fatos canônicos de curso (carga, duração, preços) derivados do catálogo."""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.pricing import band_for_hours, lookup_course_hours, price_for_course

_COURSE_LINE_RE = re.compile(r"^-\s*(.+?)\s*[—–-]\s*(\d+)\s*h", re.MULTILINE)
_HOURS_IN_TEXT_RE = re.compile(
    r"(?i)(?:(\d+)\s*h(?:oras?)?|carga\s+(?:hor[aá]ria\s+)?(?:de\s+)?(\d+))"
)
_MONTHS_IN_TEXT_RE = re.compile(
    r"(?i)(?:a\s+partir\s+de|m[ií]nimo\s+de|m[ií]n\.?|em\s+at[eé]|at[eé]|em)\s+"
    r"(\d+)\s*meses?"
)
_PRICE_RE = re.compile(r"R\$\s*([\d.]+,\d{2})", re.IGNORECASE)


@dataclass(frozen=True)
class CourseFacts:
    name: str
    hours: int
    min_months: int
    max_months: int
    monthly: str
    total_18: str
    a_vista: str

    def prompt_line(self) -> str:
        return (
            f"- {self.name}: {self.hours}h; mín. {self.min_months} meses; "
            f"máx. {self.max_months} meses; mensalidade R$ {self.monthly}; "
            f"total 18x R$ {self.total_18}; à vista R$ {self.a_vista}"
        )


def min_months_for_hours(hours: int, *, course_name: str = "") -> int:
    name = (course_name or "").casefold()
    if "engenharia de segurança" in name or (
        hours == 880 and "segurança" in name
    ):
        return 12
    if hours >= 1000:
        return 10
    return 6


@lru_cache
def _catalog_entries() -> list[tuple[str, int]]:
    root = Path(__file__).resolve().parent.parent
    path = root / "prompts" / "cursos.md"
    if not path.is_file():
        return []
    return [
        (m.group(1).strip(), int(m.group(2)))
        for m in _COURSE_LINE_RE.finditer(path.read_text(encoding="utf-8"))
    ]


def resolve_catalog_name(course: str | None) -> str | None:
    if not (course or "").strip():
        return None
    key = re.sub(r"\s+", " ", course.strip().casefold())
    best: str | None = None
    best_len = 0
    for name, _hours in _catalog_entries():
        n = name.casefold()
        if key == n:
            return name
        if key in n or n in key:
            if len(n) > best_len:
                best = name
                best_len = len(n)
    return best


def course_facts(course: str | None) -> CourseFacts | None:
    canonical = resolve_catalog_name(course)
    if not canonical:
        return None
    hours = lookup_course_hours(canonical)
    if hours is None:
        return None
    band = band_for_hours(hours)
    return CourseFacts(
        name=canonical,
        hours=hours,
        min_months=min_months_for_hours(hours, course_name=canonical),
        max_months=18,
        monthly=band.monthly,
        total_18=band.total_18,
        a_vista=band.a_vista,
    )


def facts_for_lead_state(ls: dict[str, Any]) -> list[CourseFacts]:
    seen: set[str] = set()
    out: list[CourseFacts] = []
    for key in ("curso_escolhido", "curso_recomendado", "curso_alternativo"):
        facts = course_facts(ls.get(key) if isinstance(ls, dict) else None)
        if not facts or facts.name in seen:
            continue
        seen.add(facts.name)
        out.append(facts)
    return out


def format_facts_block(facts: list[CourseFacts]) -> str:
    if not facts:
        return ""
    lines = [
        "## Fatos dos cursos em discussão (use exatamente estes)",
        "Se o lead contestar um número, confira este bloco; se ele estiver certo, "
        "corrija e agradeça — nunca insista no erro.",
    ]
    lines.extend(f.prompt_line() for f in facts)
    return "\n".join(lines)


def stock_reply_from_facts(ls: dict[str, Any], *, hint: str = "") -> str | None:
    """Frase pronta humana com fatos do curso (sem meta-fala)."""
    facts_list = facts_for_lead_state(ls)
    if not facts_list and hint:
        # tenta achar curso mencionado no texto recente
        for name, _h in _catalog_entries():
            token = name.split()[0]
            if len(token) >= 5 and token.casefold() in (hint or "").casefold():
                f = course_facts(name)
                if f:
                    facts_list = [f]
                    break
    if not facts_list:
        return None
    f = facts_list[0]
    return (
        f"A pós em {f.name} tem {f.hours}h, dá pra concluir a partir de "
        f"{f.min_months} meses (prazo máximo de {f.max_months}), e a mensalidade "
        f"é R$ {f.monthly} (total em 18x R$ {f.total_18}, ou à vista R$ {f.a_vista}). "
        f"Quer que eu te explique como funciona a matrícula?"
    )


def reply_has_wrong_course_facts(reply: str) -> str | None:
    """Se a reply atribui carga/duração/preço errado a um curso do catálogo."""
    text = reply or ""
    low = text.casefold()
    for name, hours in _catalog_entries():
        # exige menção razoável ao nome (primeiro token longo ou 20 chars)
        tokens = [t for t in re.split(r"\s+", name) if len(t) >= 5]
        if not tokens:
            continue
        mentioned = name.casefold() in low or (
            tokens[0].casefold() in low
            and any(t.casefold() in low for t in tokens[1:2] or tokens[:1])
        )
        if not mentioned:
            # match parcial: 2 tokens principais
            main = [t for t in tokens if t.casefold() not in {"para", "com", "nos", "do", "da", "de", "e"}]
            if len(main) < 2 or not all(t.casefold() in low for t in main[:2]):
                continue
        facts = course_facts(name)
        if not facts:
            continue
        # Janela local ao redor do nome (heurística: trecho inteiro se curto)
        # Carga horária citada perto do curso
        for hm in re.finditer(
            rf"(?i){re.escape(tokens[0])}.{{0,100}}?(\d+)\s*h(?:oras?)?\b",
            text,
        ):
            cited = int(hm.group(1))
            if cited != facts.hours and cited in {h for _, h in _catalog_entries()}:
                # só flagra se o número é uma carga “de catálogo” diferente
                return f"{facts.name}: {cited}h≠{facts.hours}h"
            if cited != facts.hours and abs(cited - facts.hours) >= 50:
                return f"{facts.name}: {cited}h≠{facts.hours}h"
        # “X meses” com a partir de / mínimo
        for mm in re.finditer(
            rf"(?i){re.escape(tokens[0])}.{{0,120}}?"
            rf"(?:a\s+partir\s+de|m[ií]nimo\s+de|m[ií]n\.?)\s+(\d+)\s*meses?",
            text,
        ):
            cited_m = int(mm.group(1))
            if cited_m < facts.min_months:
                return f"{facts.name}: mín.{cited_m}m<{facts.min_months}m"
        # Preço claramente de outra faixa (mensalidade citada errada)
        band = price_for_course(name)
        if not band:
            continue
        for pm in re.finditer(
            rf"(?i){re.escape(tokens[0])}.{{0,100}}?R\$\s*([\d.]+,\d{{2}})",
            text,
        ):
            amt = pm.group(1)
            allowed = {band.monthly, band.total_18, band.a_vista}
            if amt not in allowed:
                # pode ser preço genérico na mesma frase — só flagra mensalidades de tabela
                from app.pricing import allowed_money_amounts

                if amt in allowed_money_amounts() and amt not in allowed:
                    return f"{facts.name}: preço {amt} fora da faixa"
    return None
