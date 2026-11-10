"""Preparo de texto para TTS — fala casual de WhatsApp em pt-BR."""

from __future__ import annotations

import re

import httpx

from app.clients.openrouter import OpenRouterClient

ALLOWED_EXPRESSION_TAGS = ("[chuckles]", "[thoughtful]")
_ALLOWED_TAG_SET = set(ALLOWED_EXPRESSION_TAGS)
_TAG_RE = re.compile(r"\[[^\]]+\]")

_PERSONAL_DATA_RE = re.compile(
    r"(?i)\b("
    r"cpf|c\s*\.?\s*p\s*\.?\s*f|"
    r"nome\s+completo|"
    r"data\s+de\s+nascimento|nascimento|"
    r"data\s+nasc"
    r")\b"
)

# Pedido ativo de dados (≠ só mencionar CPF/documentos na explicação).
# Verbo + objeto próximo (sem .{0,50} solto — evita "envia diploma… CPF").
_REQUEST_PERSONAL_DATA_RE = re.compile(
    r"(?i)"
    r"(?:"
    r"(?:me\s+)?(?:passa|passe|manda|mande|envie|envia|confirma|informe|informa|digite|diga)\s+"
    r"(?:(?:me\s+)?(?:o|a|seu|sua|esses|essas|os|as)\s+)*"
    r"(?:cpf|c\s*\.?\s*p\s*\.?\s*f|nome\s+completo|data\s+de\s+nascimento|data\s+nasc|dados(?:\s+pessoais)?)"
    r"|"
    r"\b(?:preciso|necessito)\s+(?:(?:do|de|que\s+voc[eê]\s+(?:me\s+)?"
    r"(?:passe|mande|envie)\s+))?(?:seu\s+)?"
    r"(?:cpf|c\s*\.?\s*p\s*\.?\s*f|nome\s+completo|data\s+de\s+nascimento|dados)"
    r"|"
    r"\bqual(?:\s+[eé])?\s+(?:o\s+)?(?:seu\s+)?cpf\b"
    r"|"
    r"\bme\s+envia(?:r)?\s+(?:seu\s+)?(?:nome\s+completo|cpf|data)"
    r"|"
    r"\bpode\s+me\s+passar\s+(?:esses\s+)?dados\b"
    r"|"
    r"\b(?:cpf|nome\s+completo|data\s+de\s+nascimento)\b"
    r".{0,20}?\b(?:por\s+favor|pra\s+(?:eu|mim)|para\s+(?:eu|mim))\b"
    r")"
)

_LINK_RE = re.compile(r"https?://", re.IGNORECASE)


def build_spoken_rewrite_system(*, agent_name: str, agent_gender: str) -> str:
    gender = "f" if str(agent_gender).lower().startswith("f") else "m"
    if gender == "f":
        role = "consultora"
        concord = (
            "Fale SEMPRE no feminino (você é mulher): "
            '"obrigada", "fiquei feliz", "a consultora", "pronta", "animada".'
        )
    else:
        role = "consultor"
        concord = (
            "Fale SEMPRE no masculino: "
            '"obrigado", "fiquei feliz", "o consultor", "pronto", "animado".'
        )
    tags = ", ".join(ALLOWED_EXPRESSION_TAGS)
    return f"""Você adapta a mensagem de {agent_name} ({role}) para ÁUDIO casual de WhatsApp em pt-BR.

Objetivo: soar como pessoa falando no zap — leve, natural, humana. NÃO soar como central de atendimento nem locução.

{concord}

Estilo (obrigatório):
- Contrações: "tá", "pra", "tô", "né".
- Marcadores de conversa COM MODERAÇÃO: "então", "olha", "ó", "viu?", "né?", "tá?".
- Reticências (...) para pausas naturais.
- Frases CURTAS. Pode começar no meio do pensamento ("Ah, <nome>, ..." — use SOMENTE o nome do lead se estiver no texto; senão, nenhum nome).
- NUNCA invente nem copie nomes de pessoa de exemplos/treinos. Use SOMENTE o nome do lead (ou do aluno, se a compra for para outra pessoa) informado no pedido; se não houver, nenhum nome.
- Varie a abertura entre áudios (não repita o mesmo começo).
- No máximo 3 frases curtas. Se houver pergunta, no máximo UMA no final.
- Não invente informação. Corte links, listas, markdown, emojis.

PROIBIDO (central de atendimento):
- "entendo sua preocupação", "fique tranquilo(a)", "estou à disposição", "Olá",
  "claro!", "ótima pergunta", "entendo perfeitamente".

Pronúncia (obrigatório — o TTS soletra se errar):
- CPF → escreva "cê pê efe" (nunca "CPF" nem "C P F").
- TEA (curso/área) → "Têa" (uma palavra).
- EAD → "ead" (palavra; NÃO soletrar E A D).
- Datas por extenso (12/03/1990 → "doze de março de mil novecentos e noventa").
- Números de CPF: agrupe com naturalidade.

Tags de expressão (modelo eleven_v4) — só estas, no máximo 2, pode zero:
{tags}
Use com parcimônia para calor humano. NUNCA invente outras tags.

Saída: apenas o texto a ser falado (pode incluir as tags permitidas).
"""


def asks_or_confirms_personal_data(text: str) -> bool:
    """True se o texto menciona CPF/nome completo/nascimento (ex.: TTS)."""
    return bool(_PERSONAL_DATA_RE.search(text or ""))


def requests_personal_data(text: str) -> bool:
    """True só se a agente PEDIR dados pessoais agora (não basta mencionar).

    Lista de documentos (diploma, histórico, RG) e explicações do tipo
    "na hora de fechar você envia os dados" NÃO disparam.
    """
    raw = text or ""
    if not _PERSONAL_DATA_RE.search(raw) and not re.search(
        r"(?i)\bdados\s+(?:pessoais|completos)\b", raw
    ):
        return False
    # Pedido explícito
    if _REQUEST_PERSONAL_DATA_RE.search(raw):
        return True
    # "nome completo, CPF e data de nascimento" em tom de coleta
    if re.search(
        r"(?i)nome\s+completo.{0,40}cpf.{0,40}(?:data\s+de\s+nascimento|nascimento)",
        raw,
    ) and re.search(
        r"(?i)\b(?:manda|envie|passa|preciso|me\s+passa|pode\s+me|formalizar|preencher)\b",
        raw,
    ):
        return True
    return False


def contains_link(text: str) -> bool:
    return bool(_LINK_RE.search(text or ""))


def sanitize_expression_tags(text: str, *, allow_tags: bool = True) -> str:
    """Garante whitelist + máx. 2 tags; remove todas se allow_tags=False."""
    kept = 0

    def _replace(match: re.Match[str]) -> str:
        nonlocal kept
        raw = match.group(0)
        if not allow_tags or raw not in _ALLOWED_TAG_SET or kept >= 2:
            return ""
        kept += 1
        return raw

    cleaned = _TAG_RE.sub(_replace, text or "")
    return re.sub(r"\s{2,}", " ", cleaned).strip()


def strip_all_expression_tags(text: str) -> str:
    return sanitize_expression_tags(text, allow_tags=False)


def extract_audio_opening(spoken: str, *, max_chars: int = 28) -> str:
    plain = strip_all_expression_tags(spoken)
    plain = re.sub(r"\s+", " ", plain).strip()
    if len(plain) <= max_chars:
        return plain
    return plain[:max_chars].rsplit(" ", 1)[0].strip() or plain[:max_chars]


def scrub_for_tts(text: str) -> str:
    t = text
    t = re.sub(r"https?://\S+", "", t)
    t = re.sub(r"CHECKOUT_READY\|.*", "", t)
    t = re.sub(r"FOLLOWUP_DOC\|.*", "", t)
    t = re.sub(r"LEAD_DATA\|.*", "", t)
    t = t.replace("—", ",").replace("–", ",")
    # Preserva reticências (...); colapsa só pontuação repetida !? .
    t = re.sub(r"[*_`#>]+\s*", "", t)
    t = re.sub(r"\s*\n+\s*", ". ", t)
    t = re.sub(r"\s{2,}", " ", t)
    t = re.sub(r"([!?]){2,}", r"\1", t)
    t = re.sub(r"\.{4,}", "...", t)
    return t.strip(" ,;")


def phonetize_for_tts(text: str) -> str:
    """Corrige siglas críticas sem alterar tags [chuckles]/[thoughtful]."""
    parts: list[str] = []
    last = 0
    for m in _TAG_RE.finditer(text):
        parts.append(_phonetize_chunk(text[last : m.start()]))
        parts.append(m.group(0))
        last = m.end()
    parts.append(_phonetize_chunk(text[last:]))
    return re.sub(r"\s{2,}", " ", "".join(parts)).strip()


# Nomes que o rewrite costuma copiar dos exemplos — nunca usar se não forem do lead.
_EXAMPLE_PERSON_NAMES = frozenset(
    {
        "maria",
        "joão",
        "joao",
        "josé",
        "jose",
        "ana",
        "carlos",
        "pedro",
        "paulo",
        "lucas",
        "mariana",
        "fernanda",
        "roberto",
    }
)

# Nomes longos primeiro (Mariana antes de Maria) para não truncar o token.
_VOCATIVE_RE = re.compile(
    r"(?i)(?:^|(?<=[\s\[\]\.\!\?]))"
    r"(?:(?:ah|oi|ol[aá]|eita|n[eé]|olha),?\s+)?"
    r"(?P<name>Mariana|Fernanda|Roberto|Carlos|Pedro|Paulo|Lucas|"
    r"Maria|Jo[aã]o|Jos[eé]|Ana)"
    r"(?=\b|,|\s|$)"
    r",?\s*"
)


def allowed_spoken_names(*, lead_name: str = "", aluno_nome: str = "") -> set[str]:
    out: set[str] = set()
    for raw in (lead_name, aluno_nome):
        for part in re.split(r"\s+", (raw or "").strip()):
            p = part.strip(".,!?")
            if len(p) >= 2:
                out.add(p.casefold())
    return out


def strip_wrong_person_vocatives(
    spoken: str, *, allowed_names: set[str] | None = None
) -> str:
    """Remove vocativos com nomes de exemplo / nomes não autorizados (ex.: Maria)."""
    allowed = {n.casefold() for n in (allowed_names or set()) if n}

    def _keep_or_drop(m: re.Match[str]) -> str:
        name = m.group("name")
        key = name.casefold()
        if key in allowed:
            return m.group(0)
        if key in _EXAMPLE_PERSON_NAMES or key not in allowed:
            # Mantém tag anterior se houver; só tira o vocativo
            return ""
        return m.group(0)

    out = _VOCATIVE_RE.sub(_keep_or_drop, spoken or "")
    out = re.sub(r"\s{2,}", " ", out).strip(" ,")
    out = re.sub(r"^\[\s*", "[", out)
    return out.strip()


def spoken_has_foreign_person_name(
    spoken: str, *, allowed_names: set[str] | None = None
) -> bool:
    allowed = {n.casefold() for n in (allowed_names or set()) if n}
    for m in _VOCATIVE_RE.finditer(spoken or ""):
        key = m.group("name").casefold()
        if key not in allowed and key in _EXAMPLE_PERSON_NAMES:
            return True
    # "Ah, Maria" já coberto; também "..., Maria, ..."
    for name in _EXAMPLE_PERSON_NAMES:
        if name in allowed:
            continue
        if re.search(rf"(?i)\b{re.escape(name)}\b", spoken or ""):
            return True
    return False


def _phonetize_chunk(t: str) -> str:
    from app.money_speech import expand_money_and_hours_for_speech

    t = expand_money_and_hours_for_speech(t)
    t = re.sub(r"\bC\s*\.?\s*P\s*\.?\s*F\b", "cê pê efe", t, flags=re.IGNORECASE)
    t = re.sub(r"\bCPF\b", "cê pê efe", t, flags=re.IGNORECASE)
    t = re.sub(r"\bT\s+E\s+A\b", "Têa", t, flags=re.IGNORECASE)
    t = re.sub(r"\bTEA\b", "Têa", t)
    t = re.sub(r"\bCNPJ\b", "cê ene pê jota", t, flags=re.IGNORECASE)
    t = re.sub(r"\bRG\b", "erge", t)
    t = re.sub(r"\bE\s+A\s+D\b", "ead", t, flags=re.IGNORECASE)
    t = re.sub(r"\bEAD\b", "ead", t, flags=re.IGNORECASE)
    return t


async def to_spoken_script(
    llm: OpenRouterClient,
    written: str,
    *,
    agent_name: str = "Edu",
    agent_gender: str = "f",
    allow_expression_tags: bool = True,
    last_audio_opening: str = "",
    lead_name: str = "",
    aluno_nome: str = "",
) -> str:
    """Gera versão falada; tags só aqui (nunca no reply/histórico)."""
    cleaned = phonetize_for_tts(scrub_for_tts(written))
    if len(cleaned) < 8:
        return sanitize_expression_tags(cleaned, allow_tags=allow_expression_tags)

    allowed = allowed_spoken_names(lead_name=lead_name, aluno_nome=aluno_nome)
    name_hint = ""
    if allowed:
        name_hint = (
            "Nomes permitidos neste áudio: "
            + ", ".join(sorted(allowed))
            + ". Não use nenhum outro nome de pessoa.\n"
        )
    else:
        name_hint = "Não use nenhum nome próprio de pessoa neste áudio.\n"

    system = build_spoken_rewrite_system(agent_name=agent_name, agent_gender=agent_gender)
    avoid = ""
    if last_audio_opening:
        avoid = (
            f'\nNÃO comece igual ao áudio anterior (abertura recente: "{last_audio_opening}"). '
            "Varie a abertura.\n"
        )
    tag_hint = (
        "Pode usar até 2 tags [chuckles] e/ou [thoughtful] se couber no tom."
        if allow_expression_tags
        else "NÃO use nenhuma tag de expressão neste áudio."
    )

    async def _once(extra: str = "") -> str:
        spoken_raw = await llm.chat(
            [
                {"role": "system", "content": system},
                {
                    "role": "user",
                    "content": (
                        "Reescreva para áudio casual de WhatsApp.\n"
                        f"{tag_hint}{avoid}{name_hint}{extra}"
                        "Atenção especial a CPF (= cê pê efe), TEA (= Têa), EAD (= ead):\n\n"
                        + cleaned[:900]
                    ),
                },
            ],
            temperature=0.55,
        )
        spoken_out = phonetize_for_tts(scrub_for_tts(spoken_raw))
        spoken_out = sanitize_expression_tags(spoken_out, allow_tags=allow_expression_tags)
        spoken_out = strip_wrong_person_vocatives(spoken_out, allowed_names=allowed)
        if len(spoken_out) > 420:
            spoken_out = spoken_out[:420].rsplit(" ", 1)[0]
            spoken_out = sanitize_expression_tags(
                spoken_out, allow_tags=allow_expression_tags
            )
        return spoken_out

    try:
        spoken = await _once()
        if spoken_has_foreign_person_name(spoken, allowed_names=allowed):
            spoken = await _once(
                extra=(
                    "IMPORTANTE: remova qualquer nome inventado (ex.: Maria). "
                    "Use só o nome permitido ou nenhum nome.\n"
                )
            )
            spoken = strip_wrong_person_vocatives(spoken, allowed_names=allowed)
        return spoken or sanitize_expression_tags(cleaned, allow_tags=False)
    except (httpx.HTTPError, RuntimeError, KeyError, IndexError):
        parts = re.split(r"(?<=[.!?])\s+", cleaned)
        short = " ".join(parts[:3]).strip()
        return sanitize_expression_tags(
            strip_wrong_person_vocatives(
                phonetize_for_tts(short[:420] or cleaned),
                allowed_names=allowed,
            ),
            allow_tags=False,
        )
