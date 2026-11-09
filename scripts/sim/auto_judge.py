"""Fiscal automático — regras checadas em código."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from app.lead_state import reply_looks_like_promise
from app.speech import asks_or_confirms_personal_data

_PRICE_RE = re.compile(r"R\$\s*([\d.]+,\d{2}|\d+)", re.IGNORECASE)
_COURSE_LINE_RE = re.compile(r"^-\s*(.+?)\s*[—–-]\s*(\d+)\s*h", re.MULTILINE)
_URGENCY = (
    "últimas vagas",
    "ultimas vagas",
    "só hoje",
    "so hoje",
    "só até",
    "so ate",
    "só até sexta",
    "vagas limitadas",
    "acaba hoje",
)
_NEXT_STEP_HINTS = (
    "http",
    "manda",
    "me confirma",
    "me passa",
    "me envia",
    "seguimos",
    "próximo",
    "proximo",
    "posso te",
    "quer que",
    "vamos",
)


def load_catalog(path: Path | None = None) -> list[tuple[str, int]]:
    root = Path(__file__).resolve().parents[2]
    p = path or (root / "prompts" / "cursos.md")
    text = p.read_text(encoding="utf-8")
    out: list[tuple[str, int]] = []
    for m in _COURSE_LINE_RE.finditer(text):
        name = m.group(1).strip()
        hours = int(m.group(2))
        out.append((name, hours))
    return out


def _normalize(s: str) -> str:
    return re.sub(r"\s+", " ", s.casefold()).strip()


def _find_unknown_courses(reply: str, catalog: list[tuple[str, int]]) -> list[str]:
    """Heurística: detecta 'pós em X' / 'especialização em X' / nomes longos que não estão no catálogo."""
    known = {_normalize(n) for n, _ in catalog}
    # aliases curtos do catálogo (última parte significativa)
    for n, _ in catalog:
        parts = re.split(r"\s*[–—-]\s*", n)
        for part in parts:
            if len(part) >= 8:
                known.add(_normalize(part))

    hits: list[str] = []
    patterns = [
        r"(?:p[oó]s(?:-gradua[cç][aã]o)?|especializa[cç][aã]o)\s+em\s+([A-Za-zÀ-ÿ0-9][A-Za-zÀ-ÿ0-9\s,/]{3,80})",
        r"\b(MBA\s+Executivo\s+em\s+[A-Za-zÀ-ÿ0-9\s]{3,60})",
        r"\b(Enfermagem\s+em\s+[A-Za-zÀ-ÿ0-9\s]{3,40})",
        r"\b(Neuropsicopedagogia[A-Za-zÀ-ÿ0-9\s,]{0,60})",
        r"\b(Psicopedagogia[A-Za-zÀ-ÿ0-9\s,]{0,60})",
        r"\b(TEA\s*[–—-]?\s*Transtorno[A-Za-zÀ-ÿ0-9\s]{0,40})",
        r"\b(UTI|terapia intensiva)\b",
    ]
    for pat in patterns:
        for m in re.finditer(pat, reply, flags=re.IGNORECASE):
            raw = m.group(1).strip(" .,;:?!")
            # corta em pontuação de frase
            raw = re.split(r"[.?!\n]", raw)[0].strip()
            if len(raw) < 3:
                continue
            # genéricos ok
            if _normalize(raw) in ("graduação", "graduacao", "capacitação", "capacitacao"):
                continue
            # UTI / fora do catálogo
            if _normalize(raw) in ("uti", "terapia intensiva") or "uti" in _normalize(raw):
                if not any("uti" in k for k in known):
                    hits.append(raw)
                    continue
            # match se algum known contém ou é contido
            nr = _normalize(raw)
            if any(nr in k or k in nr for k in known if len(k) >= 6):
                continue
            # se citou nome quase igual a um do catálogo, ok
            hits.append(raw)
    # dedupe
    seen: set[str] = set()
    uniq: list[str] = []
    for h in hits:
        key = _normalize(h)
        if key not in seen:
            seen.add(key)
            uniq.append(h)
    return uniq


def judge_agent_reply(
    reply: str,
    *,
    turno: int,
    aceite_matricula: bool,
    action_executed: bool,
    catalog: list[tuple[str, int]] | None = None,
) -> list[dict[str, Any]]:
    catalog = catalog or load_catalog()
    text = (reply or "").strip()
    violations: list[dict[str, Any]] = []

    def add(regra: str, trecho: str) -> None:
        violations.append({"turno": turno, "regra": regra, "trecho": trecho[:180]})

    if not text:
        add("sem_pergunta_nem_proximo_passo", "(resposta vazia)")
        return violations

    # preço: só 69,90 é permitido
    for m in _PRICE_RE.finditer(text):
        if not re.search(r"69\s*[,.]\s*90", m.group(0)):
            add("preco_diferente_69_90", m.group(0))

    # perguntas: resposta inteira
    q_count = text.count("?")
    if q_count > 1:
        add("mais_de_uma_pergunta", f"{q_count} interrogacoes")

    low = text.casefold()
    has_next = any(h in low for h in _NEXT_STEP_HINTS) or "http" in low
    if q_count == 0 and not has_next:
        add("sem_pergunta_nem_proximo_passo", text[:120])

    if asks_or_confirms_personal_data(text) and not aceite_matricula:
        add("cpf_antes_de_aceite", text[:120])

    if reply_looks_like_promise(text) and not action_executed:
        add("promessa_sem_acao", text[:120])

    for u in _URGENCY:
        if u in low:
            add("urgencia_escassez", u)
            break

    # 6 meses + curso 1000h+
    if re.search(r"\b6\s*meses\b", low):
        for name, hours in catalog:
            if hours >= 1000 and _normalize(name.split("—")[0].split("–")[0])[:20] in _normalize(text):
                # match course name fragment in reply
                frag = name.split("—")[0].split("–")[0].strip()
                if len(frag) >= 6 and frag.casefold() in low:
                    add("seis_meses_curso_1000h", f"{frag} ({hours}h)")
                    break
        # também Autismo / Educação Especial se citados
        for name, hours in catalog:
            if hours < 1000:
                continue
            short = name.split("—")[0].split("–")[0].strip().casefold()
            token = short.split()[0]
            if len(token) >= 5 and token in low and short.split()[0] in low:
                # if any long course keyword present
                if any(w in low for w in short.split()[:2]):
                    add("seis_meses_curso_1000h", f"{name} ({hours}h)")
                    break

    if "[chuckles]" in text or "[thoughtful]" in text:
        add("tag_audio_no_texto", text[:80])
    if '"reply"' in text or "```" in text or text.strip().startswith("{"):
        add("json_no_texto", text[:80])

    for bad in _find_unknown_courses(text, catalog):
        add("curso_fora_catalogo", bad)

    return violations
