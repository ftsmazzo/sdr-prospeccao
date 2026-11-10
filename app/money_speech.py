"""Converte valores em reais e cargas horárias para fala (TTS)."""

from __future__ import annotations

import re

from app.pricing import _ALL_BANDS

_UNIDADES = (
    "zero",
    "um",
    "dois",
    "três",
    "quatro",
    "cinco",
    "seis",
    "sete",
    "oito",
    "nove",
)
_ESPECIAIS = {
    10: "dez",
    11: "onze",
    12: "doze",
    13: "treze",
    14: "quatorze",
    15: "quinze",
    16: "dezesseis",
    17: "dezessete",
    18: "dezoito",
    19: "dezenove",
}
_DEZENAS = (
    "",
    "",
    "vinte",
    "trinta",
    "quarenta",
    "cinquenta",
    "sessenta",
    "setenta",
    "oitenta",
    "noventa",
)
_CENTENAS = (
    "",
    "cento",
    "duzentos",
    "trezentos",
    "quatrocentos",
    "quinhentos",
    "seiscentos",
    "setecentos",
    "oitocentos",
    "novecentos",
)


def _under_100(n: int, *, feminine: bool = False) -> str:
    if n < 10:
        if feminine and n == 1:
            return "uma"
        if feminine and n == 2:
            return "duas"
        return _UNIDADES[n]
    if n in _ESPECIAIS:
        return _ESPECIAIS[n]
    d, u = divmod(n, 10)
    if u == 0:
        return _DEZENAS[d]
    unit = _under_100(u, feminine=feminine)
    return f"{_DEZENAS[d]} e {unit}"


def _under_1000(n: int, *, feminine: bool = False) -> str:
    if n < 100:
        return _under_100(n, feminine=feminine)
    if n == 100:
        return "cem"
    c, rest = divmod(n, 100)
    head = _CENTENAS[c]
    if feminine and c == 2:
        head = "duzentas"
    elif feminine and c == 3:
        head = "trezentas"
    elif feminine and c >= 4:
        # quatrocentas … novecentas
        head = (
            "",
            "",
            "duzentas",
            "trezentas",
            "quatrocentas",
            "quinhentas",
            "seiscentas",
            "setecentas",
            "oitocentas",
            "novecentas",
        )[c]
    if rest == 0:
        return head
    return f"{head} e {_under_100(rest, feminine=feminine)}"


def integer_to_pt(n: int, *, feminine: bool = False) -> str:
    """Inteiro 0..999_999 em pt-BR."""
    n = int(n)
    if n < 0:
        return "menos " + integer_to_pt(-n, feminine=feminine)
    if n < 1000:
        return _under_1000(n, feminine=feminine)
    milhares, rest = divmod(n, 1000)
    if milhares == 1:
        head = "mil"
    else:
        head = f"{_under_1000(milhares, feminine=False)} mil"
    if rest == 0:
        return head
    if rest < 100 or rest % 100 == 0:
        return f"{head} e {_under_1000(rest, feminine=feminine)}"
    return f"{head} {_under_1000(rest, feminine=feminine)}"


def brl_amount_to_spoken(amount: str) -> str:
    """'79,90' ou '1.438,20' → 'setenta e nove reais e noventa centavos'."""
    raw = (amount or "").strip()
    raw = raw.replace("R$", "").strip()
    raw = raw.replace(" ", "")
    if not re.fullmatch(r"\d{1,3}(?:\.\d{3})*,\d{2}|\d+,\d{2}", raw):
        # tenta só dígitos e vírgula
        if not re.search(r"\d", raw):
            return amount
    whole_s, _, cents_s = raw.partition(",")
    whole_s = whole_s.replace(".", "") or "0"
    cents_s = (cents_s + "00")[:2]
    whole = int(whole_s)
    cents = int(cents_s)
    if whole == 0:
        reais = "zero reais"
    elif whole == 1:
        reais = "um real"
    else:
        reais = f"{integer_to_pt(whole)} reais"
    if cents == 0:
        return reais
    if cents == 1:
        return f"{reais} e um centavo"
    return f"{reais} e {integer_to_pt(cents)} centavos"


def hours_to_spoken(hours: int | str) -> str:
    """750 → 'setecentas e cinquenta horas'."""
    h = int(hours)
    if h == 1:
        return "uma hora"
    # horas é feminino na concordância de quantidade falada comum
    return f"{integer_to_pt(h, feminine=True)} horas"


_MONEY_RE = re.compile(r"R\$\s*(\d{1,3}(?:\.\d{3})*,\d{2}|\d+,\d{2})", re.IGNORECASE)
_HOURS_RE = re.compile(r"\b(\d{2,4})\s*h(?:oras?)?\b", re.IGNORECASE)
# "79,90" / "1.438,20" soltos perto de mensalidade (sem R$)
_BARE_MONEY_RE = re.compile(r"(?<![\d.])(\d{1,3}(?:\.\d{3})*,\d{2})(?!\d)")


def expand_money_and_hours_for_speech(text: str) -> str:
    """Substitui R$ X e Nh por forma falada antes do TTS."""
    t = text or ""

    def _money(m: re.Match[str]) -> str:
        return brl_amount_to_spoken(m.group(1))

    t = _MONEY_RE.sub(_money, t)

    def _hours(m: re.Match[str]) -> str:
        return hours_to_spoken(int(m.group(1)))

    t = _HOURS_RE.sub(_hours, t)

    # valores da tabela sem R$ (ex.: "mensalidade é 79,90")
    allowed = set()
    for b in _ALL_BANDS:
        allowed.add(b.monthly)
        allowed.add(b.total_18)
        allowed.add(b.a_vista)

    def _bare(m: re.Match[str]) -> str:
        amt = m.group(1)
        if amt in allowed:
            return brl_amount_to_spoken(amt)
        return amt

    t = _BARE_MONEY_RE.sub(_bare, t)
    return t


def all_table_amounts() -> list[str]:
    out: list[str] = []
    for b in _ALL_BANDS:
        out.extend([b.monthly, b.total_18, b.a_vista])
    return out
