"""Tabela de mensalidades por faixa de carga horária (demo)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


@dataclass(frozen=True)
class PriceBand:
    monthly: str  # "79,90"
    total_18: str  # "1.438,20"
    a_vista: str  # "1.294,38"

    @property
    def monthly_label(self) -> str:
        return f"R$ {self.monthly}"

    @property
    def total_18_label(self) -> str:
        return f"R$ {self.total_18}"

    @property
    def a_vista_label(self) -> str:
        return f"R$ {self.a_vista}"


BAND_ATE_520 = PriceBand("69,90", "1.258,20", "1.132,38")
BAND_620_750 = PriceBand("79,90", "1.438,20", "1.294,38")
BAND_880_1000 = PriceBand("89,90", "1.618,20", "1.456,38")

_ALL_BANDS = (BAND_ATE_520, BAND_620_750, BAND_880_1000)


def band_for_hours(hours: int) -> PriceBand:
    """Mapeia carga horária → faixa. Gaps da tabela: 521–619 → faixa média; >750 → faixa alta."""
    if hours <= 520:
        return BAND_ATE_520
    if hours <= 750:
        return BAND_620_750
    return BAND_880_1000


@lru_cache
def _course_hours_map() -> dict[str, int]:
    root = Path(__file__).resolve().parent.parent
    path = root / "prompts" / "cursos.md"
    if not path.is_file():
        return {}
    out: dict[str, int] = {}
    for m in re.finditer(
        r"^-\s*(.+?)\s*[—–-]\s*(\d+)\s*h",
        path.read_text(encoding="utf-8"),
        flags=re.MULTILINE,
    ):
        name = m.group(1).strip()
        hours = int(m.group(2))
        out[_norm(name)] = hours
        # alias: parte após traço tipográfico já está no nome; também última parte curta
        parts = re.split(r"\s*[–—-]\s*", name)
        for part in parts:
            p = part.strip()
            if len(p) >= 6:
                out.setdefault(_norm(p), hours)
    return out


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").casefold()).strip()


def lookup_course_hours(course: str | None) -> int | None:
    if not course:
        return None
    table = _course_hours_map()
    key = _norm(course)
    if key in table:
        return table[key]
    # match parcial
    for name, hours in table.items():
        if key in name or name in key:
            return hours
    return None


def price_for_course(course: str | None) -> PriceBand | None:
    hours = lookup_course_hours(course)
    if hours is None:
        return None
    return band_for_hours(hours)


def amount_label_for_course(course: str | None) -> str:
    """Rótulo de mensalidade para checkout/PDF; fallback genérico se curso desconhecido."""
    band = price_for_course(course)
    if not band:
        return "a partir de R$ 69,90"
    return band.monthly_label


def allowed_money_amounts() -> frozenset[str]:
    """Tokens numéricos BR permitidos pelo fiscal (sem 'R$')."""
    vals: set[str] = set()
    for b in _ALL_BANDS:
        vals.add(b.monthly)
        vals.add(b.total_18)
        vals.add(b.a_vista)
    try:
        from app.desconto_negocio import all_negociated_avista_tokens

        vals |= all_negociated_avista_tokens()
    except Exception:  # noqa: BLE001
        pass
    return frozenset(vals)
