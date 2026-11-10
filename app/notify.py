"""Notificações WhatsApp para especialistas (handoff / matrícula)."""

from __future__ import annotations

import logging
import re
from typing import Any, Protocol

logger = logging.getLogger("edu.notify")

_CPF_RE = re.compile(r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b")
_DATE_RE = re.compile(
    r"\b(?:\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}-\d{2}-\d{2})\b"
)


class _TextSender(Protocol):
    async def send_text(self, phone: str, text: str, delay_ms: int = 0) -> dict: ...


def parse_notify_numbers(raw: str | None) -> list[str]:
    out: list[str] = []
    for part in (raw or "").split(","):
        digits = re.sub(r"\D", "", part.strip())
        if digits and digits not in out:
            out.append(digits)
    return out


def is_internal_number(phone: str, notify_numbers: list[str]) -> bool:
    digits = re.sub(r"\D", "", phone or "")
    return bool(digits) and digits in notify_numbers


def scrub_notify_text(text: str) -> str:
    t = _CPF_RE.sub("[omitido]", text or "")
    t = _DATE_RE.sub("[omitido]", t)
    return t


def build_handoff_notify_message(
    *,
    agent_name: str,
    lead_nome: str | None,
    lead_phone: str,
    motivo: str,
    curso: str | None,
    etapa: str | None,
    briefing: str | None,
) -> str:
    nome = (lead_nome or "Lead").strip() or "Lead"
    motivo_l = (motivo or "sua dúvida").replace("_", " ").strip()
    curso_l = (curso or "não definido").strip()
    etapa_l = (etapa or "?").strip()
    resumo = scrub_notify_text((briefing or "").strip() or "(sem briefing ainda)")
    phone_digits = re.sub(r"\D", "", lead_phone or "") or (lead_phone or "")
    body = (
        f"Novo encaminhamento — {agent_name}\n"
        f"Lead: {nome} ({phone_digits})\n"
        f"Motivo: {motivo_l}\n"
        f"Curso: {curso_l}\n"
        f"Etapa: {etapa_l}\n"
        f"Resumo: {resumo}"
    )
    return scrub_notify_text(body)


def build_matricula_notify_message(
    *,
    agent_name: str,
    lead_nome: str | None,
    lead_phone: str,
    curso: str | None,
    aluno_nome: str | None = None,
    comprador_nome: str | None = None,
) -> str:
    phone = re.sub(r"\D", "", lead_phone or "") or lead_phone
    curso_l = (curso or "curso").strip()
    aluno = (aluno_nome or lead_nome or "Aluno").strip() or "Aluno"
    comprador = (comprador_nome or lead_nome or "").strip()
    if comprador and aluno.casefold() != comprador.casefold():
        who = f"Aluno: {aluno} — compra feita por {comprador} ({phone})"
    else:
        who = f"Lead: {aluno} ({phone})"
    return (
        f"Matrícula confirmada — {agent_name}\n"
        f"{who}\n"
        f"Curso: {curso_l}"
    )


async def notify_numbers(
    sender: _TextSender,
    numbers: list[str],
    message: str,
    *,
    exclude_phone: str | None = None,
) -> int:
    """Envia para cada número; falhas só no log. Retorna qtd enviada."""
    exclude = re.sub(r"\D", "", exclude_phone or "")
    sent = 0
    text = scrub_notify_text(message)
    for num in numbers:
        if exclude and num == exclude:
            continue
        try:
            await sender.send_text(num, text, delay_ms=0)
            sent += 1
        except Exception:  # noqa: BLE001
            logger.exception("falha ao notificar especialista phone=%s", num)
    return sent
