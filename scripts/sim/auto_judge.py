"""Fiscal automático — regras checadas em código."""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from typing import Any

from app.lead_state import reply_looks_like_promise
from app.pricing import allowed_money_amounts
from app.speech import requests_personal_data
from app.course_facts import reply_has_wrong_course_facts
from app.offers import lead_affirms_offer
from app.orchestrator import replies_nearly_equal
from app.veracity import (
    claims_unbacked_action,
    lead_refuses_question,
    lead_says_sending_document,
    reply_asks_objetivo,
    reply_has_invented_policy,
    reply_has_markdown_list,
)

_PRICE_RE = re.compile(r"R\$\s*([\d.]+,\d{2})", re.IGNORECASE)
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

# Despedida / pedido de espaço do lead (fiscal + harness).
_FAREWELL_RES: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bat[eé]\s+mais\b", re.IGNORECASE),
    re.compile(r"\bat[eé]\s+logo\b", re.IGNORECASE),
    re.compile(r"\btchau\b", re.IGNORECASE),
    re.compile(r"\bfalamos\s+depois\b", re.IGNORECASE),
    re.compile(r"\b(vou|preciso|prefiro|quero)\s+pensar\b", re.IGNORECASE),
    re.compile(r"\bpensar\s+(um\s+pouco|mais|com\s+calma|direitinho|melhor)\b", re.IGNORECASE),
    re.compile(r"\bentro\s+em\s+contato\b", re.IGNORECASE),
    re.compile(r"\bentrarei\s+em\s+contato\b", re.IGNORECASE),
    re.compile(r"\bvolto\s+a\s+entrar\s+em\s+contato\b", re.IGNORECASE),
    re.compile(
        r"\bvolto\s+a\s+falar\s+(?:com\s+voc[eê]|depois|mais\s+tarde)\b",
        re.IGNORECASE,
    ),
    re.compile(r"\bte\s+aviso\b", re.IGNORECASE),
    re.compile(r"\bte\s+falo\b", re.IGNORECASE),
    re.compile(r"\bte\s+dou\s+um\s+retorno\b", re.IGNORECASE),
    re.compile(r"\bdou\s+um\s+retorno\b", re.IGNORECASE),
    re.compile(r"\bdepois\s+(te\s+)?(falo|aviso|retorno)\b", re.IGNORECASE),
    re.compile(r"\b(vou|quero)\s+(avaliar|analisar)\b", re.IGNORECASE),
    re.compile(r"\bcontinu(?:o|arei)\s+avaliando\b", re.IGNORECASE),
    re.compile(r"\bpor\s+enquanto\s+(é|e)\s+s[oó]\b", re.IGNORECASE),
    re.compile(
        r"\bpor\s+enquanto[,.]?\s+(n[aã]o(\s+preciso)?|s[oó]\s+(isso|tirar)|"
        r"prefiro\s+pensar|vou\s+pensar|continu)\b",
        re.IGNORECASE,
    ),
    re.compile(r"\bqualquer\s+coisa[,.]?\s+(eu\s+)?(entro|pe[cç]o|aviso)\b", re.IGNORECASE),
    re.compile(r"\bse\s+eu\s+(decidir|precisar)\b", re.IGNORECASE),
    re.compile(r"\b(depois|mais\s+tarde)\s+(eu\s+)?(te\s+)?aviso\b", re.IGNORECASE),
    re.compile(r"\bn[aã]o\s+precisa\b", re.IGNORECASE),
    re.compile(r"\bvou\s+aguardar\b", re.IGNORECASE),
    re.compile(r"\b(deixa|deixar)\s+pra\s+(l[aá]|depois)\b", re.IGNORECASE),
    re.compile(r"\bquando\s+decidir\b", re.IGNORECASE),
    re.compile(
        r"\btenha\s+(?:um|uma)\s+(?:[oó]timo|bom|excelente|boa)\s+"
        r"(?:dia|tarde|noite)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bobrigad[oa]\s+pela\s+(?:aten[cç][aã]o|paci[eê]ncia|disponibilidade|"
        r"cordialidade|ajuda|confirma[cç][aã]o)\b",
        re.IGNORECASE,
    ),
)


def looks_like_farewell(text: str) -> bool:
    """True se o lead parece se despedir ou pedir espaço."""
    raw = (text or "").strip()
    if not raw:
        return False
    return any(rx.search(raw) for rx in _FAREWELL_RES)


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
    """Casefold + remove acentos + unifica travessões/hífens."""
    t = unicodedata.normalize("NFD", s or "")
    t = "".join(ch for ch in t if unicodedata.category(ch) != "Mn")
    t = t.casefold()
    t = re.sub(r"[–—−‐-]+", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def _catalog_name_matches(raw: str, catalog_names: list[str]) -> bool:
    """True se raw corresponde a algum nome do catálogo (acentos/travessão/parcial)."""
    nr = _normalize(raw)
    if not nr or len(nr) < 3:
        return False
    first_raw = nr.split()[0]
    for name in catalog_names:
        kn = _normalize(name)
        if not kn:
            continue
        if nr == kn or nr in kn or kn in nr:
            return True
        first_cat = kn.split()[0]
        # Prefixo do catálogo: "Psicopedagogia …" ou "TEA tem carga…"
        if first_raw == first_cat and len(first_cat) >= 3:
            if len(first_cat) >= 8 or kn.startswith(first_raw + " "):
                return True
        # tokens significativos (≥4 chars), exige ≥2 em comum
        raw_toks = [t for t in nr.split() if len(t) >= 4]
        cat_toks = [t for t in kn.split() if len(t) >= 4]
        if len(raw_toks) >= 2 and len(cat_toks) >= 2:
            # só os tokens que também existem no catálogo contam
            overlap = [rt for rt in raw_toks if any(rt == ct or rt in ct or ct in rt for ct in cat_toks)]
            if len(overlap) >= 2 or (len(overlap) >= 1 and len(first_cat) >= 8 and first_raw == first_cat):
                return True
    return False


# Áreas / rótulos genéricos — não são nome de curso do catálogo.
_GENERIC_COURSE_LABELS = {
    "saúde",
    "saude",
    "enfermagem",
    "educação",
    "educacao",
    "pedagogia",
    "negócios",
    "negocios",
    "direito",
    "tecnologia",
    "bem-estar",
    "bem estar",
    "graduação",
    "graduacao",
    "capacitação",
    "capacitacao",
    "pós",
    "pos",
    "especialização",
    "especializacao",
    "área da saúde",
    "area da saude",
    "área de saúde",
    "area de saude",
}

_DENIAL_RE = re.compile(
    r"(?:"
    r"n[aã]o\s+(?:temos|est[aá]|consta|oferecemos|disponibilizamos)|"
    r"n[aã]o\s+est[aá]\s+(?:no|na)\s+(?:cat[aá]logo|lista)|"
    r"fora\s+do\s+cat[aá]logo|"
    r"n[aã]o\s+temos\s+na\s+lista|"
    r"n[aã]o\s+faz\s+parte\s+do\s+cat[aá]logo"
    r")",
    re.IGNORECASE,
)


def _trim_course_capture(raw: str) -> str:
    """Corta o nome capturado em conectores/frases (evita engolir a sentença)."""
    cut = re.split(
        r"\s+(?:n[aã]o|nao|mas|por[eé]m|para|pra|que|com|,|;|:)\s+",
        raw or "",
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0]
    words = cut.strip().split()
    if len(words) > 8:
        cut = " ".join(words[:8])
    return cut.strip(" .,;:?!-–—")


def _is_generic_course_label(raw: str) -> bool:
    nr = _normalize(raw)
    if not nr:
        return True
    if nr in _GENERIC_COURSE_LABELS:
        return True
    first = nr.split()[0]
    return bool(first in _GENERIC_COURSE_LABELS and len(nr.split()) <= 4)


def _lead_mentioned_course(lead_text: str, course_raw: str) -> bool:
    lead_n = _normalize(lead_text)
    course_n = _normalize(course_raw)
    if not lead_n or not course_n:
        return False
    if course_n in lead_n:
        return True
    # tokens significativos (ex.: UTI, terapia intensiva)
    for tok in course_n.split()[:3]:
        if len(tok) >= 3 and re.search(rf"\b{re.escape(tok)}\b", lead_n):
            return True
    return bool(len(course_n) <= 4 and re.search(rf"\b{re.escape(course_n)}\b", lead_n))


def _find_unknown_courses(
    reply: str,
    catalog: list[tuple[str, int]],
    *,
    lead_text: str = "",
) -> list[str]:
    """Heurística: detecta 'pós em X' / 'especialização em X' / nomes longos que não estão no catálogo."""
    catalog_names = [n for n, _ in catalog]
    known = {_normalize(n) for n in catalog_names}

    reply_denies = bool(_DENIAL_RE.search(reply or ""))
    hits: list[str] = []
    patterns = [
        r"(?:p[oó]s(?:-gradua[cç][aã]o)?|especializa[cç][aã]o)\s+em\s+([A-Za-zÀ-ÿ0-9][A-Za-zÀ-ÿ0-9\s,/–—-]{3,80})",
        r"\b(MBA\s+Executivo\s+em\s+[A-Za-zÀ-ÿ0-9\s]{3,60})",
        r"\b(Enfermagem\s+em\s+[A-Za-zÀ-ÿ0-9\s]{3,40})",
        r"\b(Neuropsicopedagogia[A-Za-zÀ-ÿ0-9\s,]{0,60})",
        r"\b(Psicopedagogia[A-Za-zÀ-ÿ0-9\s,]{0,60})",
        r"\b(TEA\s*[–—-]?\s*Transtorno[A-Za-zÀ-ÿ0-9\s]{0,50})",
        r"\b(UTI|terapia intensiva)\b",
    ]
    for pat in patterns:
        for m in re.finditer(pat, reply, flags=re.IGNORECASE):
            raw = m.group(1).strip(" .,;:?!")
            raw = re.split(r"[.?!\n]", raw)[0].strip()
            raw = _trim_course_capture(raw)
            if len(raw) < 3:
                continue
            if _is_generic_course_label(raw):
                continue
            if reply_denies and _lead_mentioned_course(lead_text, raw):
                continue
            nr = _normalize(raw)
            if nr in ("uti", "terapia intensiva") or re.search(r"\buti\b", nr):
                known_has_uti = any(re.search(r"\buti\b", k) for k in known)
                if (not known_has_uti) and not (
                    reply_denies and _lead_mentioned_course(lead_text, raw)
                ):
                    hits.append("UTI" if re.search(r"\buti\b", nr) else raw)
                continue
            if _catalog_name_matches(raw, catalog_names):
                continue
            hits.append(raw)
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
    lead_text: str = "",
    has_media: bool = False,
    just_entered_handoff: bool = False,
    handoff_avisado: bool = False,
    delivery_ran: bool = False,
    handoff_registered_this_turn: bool = False,
    handoff_registrado: bool = False,
    prev_agent_asked_objetivo: bool = False,
    lead_refused_objetivo: bool = False,
    asked_objetivo_after_refuse_count: int = 0,
    recent_agent_replies: list[str] | None = None,
    pending_offer_before: dict | None = None,
    pending_offer_after: dict | None = None,
    pending_offer_executed: bool = False,
) -> list[dict[str, Any]]:
    catalog = catalog or load_catalog()
    text = (reply or "").strip()
    violations: list[dict[str, Any]] = []

    def add(regra: str, trecho: str) -> None:
        violations.append({"turno": turno, "regra": regra, "trecho": trecho[:180]})

    if not text:
        add("sem_pergunta_nem_proximo_passo", "(resposta vazia)")
        return violations

    # preço: somente valores da tabela prompts/precos.md
    allowed = allowed_money_amounts()
    for m in _PRICE_RE.finditer(text):
        amount = m.group(1).strip()
        if amount not in allowed:
            add("preco_fora_tabela", m.group(0))

    fake = claims_unbacked_action(
        text,
        has_media=has_media,
        just_entered_handoff=just_entered_handoff,
        handoff_avisado=handoff_avisado,
        delivery_ran=delivery_ran or action_executed,
        handoff_registered_this_turn=handoff_registered_this_turn,
        handoff_registrado=handoff_registrado,
        lead_sending_document=lead_says_sending_document(lead_text),
    )
    if fake:
        add("acao_fingida", f"{fake}: {text[:100]}")

    if reply_has_invented_policy(text):
        add("politica_inventada", text[:120])

    wrong = reply_has_wrong_course_facts(text)
    if wrong:
        add("fato_curso_errado", wrong)

    if reply_has_markdown_list(text):
        add("lista_markdown", text[:120])

    for prior in (recent_agent_replies or [])[:3]:
        if prior and replies_nearly_equal(text, prior):
            add("quase_igual", text[:120])
            break

    # Lead afirmou oferta pendente e nada executou / resolveu neste turno.
    if (
        pending_offer_before
        and lead_affirms_offer(lead_text)
        and not pending_offer_executed
        and not action_executed
        and not handoff_registered_this_turn
        and pending_offer_after is not None
        and pending_offer_after == pending_offer_before
    ):
        add("sim_sem_execucao", f"offer={pending_offer_before.get('type')}")

    if lead_refused_objetivo and reply_asks_objetivo(text):
        # 2ª+ pergunta de objetivo após recusa
        if asked_objetivo_after_refuse_count >= 1 or prev_agent_asked_objetivo:
            add("pergunta_repetida", text[:120])
    elif lead_refuses_question(lead_text) and reply_asks_objetivo(text) and prev_agent_asked_objetivo:
        add("pergunta_repetida", text[:120])

    # perguntas: resposta inteira
    q_count = text.count("?")
    if q_count > 1:
        add("mais_de_uma_pergunta", f"{q_count} interrogacoes")

    low = text.casefold()
    has_next = any(h in low for h in _NEXT_STEP_HINTS) or "http" in low
    lead_farewell = looks_like_farewell(lead_text)
    if q_count == 0 and not has_next and not lead_farewell:
        add("sem_pergunta_nem_proximo_passo", text[:120])

    if requests_personal_data(text) and not aceite_matricula:
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
            if (
                len(token) >= 5
                and token in low
                and any(w in low for w in short.split()[:2])
            ):
                add("seis_meses_curso_1000h", f"{name} ({hours}h)")
                break

    if "[chuckles]" in text or "[thoughtful]" in text:
        add("tag_audio_no_texto", text[:80])
    if '"reply"' in text or "```" in text or text.strip().startswith("{"):
        add("json_no_texto", text[:80])

    for bad in _find_unknown_courses(text, catalog, lead_text=lead_text):
        add("curso_fora_catalogo", bad)

    return violations
