"""Briefing de continuidade (modelo barato, pós-resposta)."""

from __future__ import annotations

import logging
import re
from typing import Any, Protocol

logger = logging.getLogger("edu.briefing")

_CPF_RE = re.compile(r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b")
_DATE_RE = re.compile(
    r"\b(?:\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}-\d{2}-\d{2})\b"
)

BRIEFING_SYSTEM = """Você atualiza um BRIEFING interno da conversa de matrícula (WhatsApp).
Regras:
- Máximo ~150 palavras, português, frases curtas.
- NÃO invente fatos. Use só o briefing anterior + mensagens novas.
- NUNCA inclua CPF, data de nascimento, RG, CNH nem documentos.
- Estrutura fixa com estas linhas (pule o que não souber):
  Lead/aluno:
  Decisões:
  Ofertas e respostas:
  Dúvidas/objeções:
  Pendências/próximo passo:
  Matrículas concluídas:
"""


class _ChatLLM(Protocol):
    async def chat(
        self,
        messages: list[dict],
        *,
        temperature: float | None = ...,
        model: str | None = ...,
    ) -> str: ...


def scrub_sensitive(text: str) -> str:
    t = _CPF_RE.sub("[dado omitido]", text or "")
    t = _DATE_RE.sub("[data omitida]", t)
    return t


def build_briefing_user_payload(
    *,
    previous: str,
    recent_messages: list[dict[str, str]],
    matriculas: list[dict[str, Any]] | None = None,
) -> str:
    lines = ["Briefing anterior:", previous.strip() or "(vazio)", "", "Mensagens novas:"]
    for m in recent_messages[-8:]:
        role = m.get("role") or "?"
        content = scrub_sensitive(str(m.get("content") or ""))[:400]
        lines.append(f"{role}: {content}")
    if matriculas:
        bits = []
        for item in matriculas:
            if isinstance(item, dict) and item.get("curso"):
                bits.append(
                    f"{item['curso']} ({item.get('aluno_nome') or '?'})"
                )
        lines.append("")
        lines.append("Matrículas no sistema: " + ("; ".join(bits) if bits else "nenhuma"))
    lines.append("")
    lines.append("Escreva o briefing atualizado (sem CPF/nascimento):")
    return "\n".join(lines)


async def refresh_briefing(
    llm: _ChatLLM,
    *,
    previous: str,
    recent_messages: list[dict[str, str]],
    matriculas: list[dict[str, Any]] | None = None,
    model: str = "openai/gpt-4.1-mini",
) -> str:
    """Gera novo briefing; em falha devolve o anterior (ou vazio)."""
    user = build_briefing_user_payload(
        previous=previous,
        recent_messages=recent_messages,
        matriculas=matriculas,
    )
    try:
        out = await llm.chat(
            [
                {"role": "system", "content": BRIEFING_SYSTEM},
                {"role": "user", "content": user},
            ],
            temperature=0.2,
            model=model,
        )
        cleaned = scrub_sensitive((out or "").strip())
        # hard cap ~150 palavras
        words = cleaned.split()
        if len(words) > 160:
            cleaned = " ".join(words[:150])
        return cleaned or previous
    except Exception:  # noqa: BLE001
        logger.exception("falha ao atualizar briefing")
        return previous or ""
