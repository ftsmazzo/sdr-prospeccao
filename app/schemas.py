"""Schemas de resposta estruturada do Edu."""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError

logger = logging.getLogger("edu.schemas")

ActionType = Literal["LEAD_DATA", "FOLLOWUP_DOC", "CHECKOUT_READY", "REGISTER_HANDOFF"]
OfferType = Literal["contrato", "encaminhamento", "resumo"]

NEUTRAL_REPLY = "Só um instante, me confirma de novo o que você precisa?"


class OfferPayload(BaseModel):
    type: OfferType
    motivo: str | None = None


class AgentResponse(BaseModel):
    reply: str = Field(min_length=1)
    state_update: dict[str, Any] = Field(default_factory=dict)
    action: ActionType | None = None
    action_data: dict[str, Any] = Field(default_factory=dict)
    offer: OfferPayload | None = None


RESPONDER_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "responder",
        "description": (
            "Emite a resposta estruturada ao lead no WhatsApp. "
            "Sempre chame esta ferramenta com reply + state_update + action + offer."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "reply": {"type": "string", "minLength": 1},
                "state_update": {"type": "object"},
                "action": {
                    "type": ["string", "null"],
                    "enum": [
                        "LEAD_DATA",
                        "FOLLOWUP_DOC",
                        "CHECKOUT_READY",
                        "REGISTER_HANDOFF",
                        None,
                    ],
                },
                "action_data": {"type": "object"},
                "offer": {
                    "anyOf": [
                        {
                            "type": "object",
                            "properties": {
                                "type": {
                                    "type": "string",
                                    "enum": ["contrato", "encaminhamento", "resumo"],
                                },
                                "motivo": {"type": ["string", "null"]},
                            },
                            "required": ["type"],
                        },
                        {"type": "null"},
                    ]
                },
            },
            "required": ["reply", "state_update"],
            "additionalProperties": True,
        },
    },
}

RESPONDER_TOOL_CHOICE: dict[str, Any] = {
    "type": "function",
    "function": {"name": "responder"},
}


def _strip_fences(raw: str) -> str:
    t = raw.strip()
    if t.startswith("```"):
        t = re.sub(r"^```(?:json)?\s*", "", t, flags=re.IGNORECASE)
        t = re.sub(r"\s*```$", "", t)
    return t.strip()


def _extract_reply_field(raw: str) -> str | None:
    """Tenta extrair só o campo reply de um JSON parcialmente inválido."""
    m = re.search(r'"reply"\s*:\s*"((?:\\.|[^"\\])*)"', raw, flags=re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(f'"{m.group(1)}"')
    except json.JSONDecodeError:
        return m.group(1).replace('\\"', '"').replace("\\n", "\n")


def looks_like_json(text: str) -> bool:
    t = text.strip()
    return t.startswith(("{", "```"))


def parse_agent_response(raw: str) -> AgentResponse | None:
    cleaned = _strip_fences(raw)
    try:
        data = json.loads(cleaned)
        if isinstance(data, dict):
            return AgentResponse.model_validate(data)
    except (json.JSONDecodeError, ValidationError, TypeError):
        pass
    # às vezes o modelo devolve objeto embutido em texto
    m = re.search(r"\{[\s\S]*\}", cleaned)
    if m:
        try:
            return AgentResponse.model_validate(json.loads(m.group(0)))
        except (json.JSONDecodeError, ValidationError, TypeError):
            return None
    return None


def safe_fallback_response(raw: str) -> AgentResponse:
    """Nunca devolve JSON bruto ao lead."""
    extracted = _extract_reply_field(raw)
    if extracted and not looks_like_json(extracted):
        reply = extracted.strip()
    else:
        reply = NEUTRAL_REPLY
    logger.error(
        "JSON inválido após retry — usando fallback. bruto=%r",
        (raw or "")[:800],
    )
    return AgentResponse(reply=reply, state_update={}, action=None, action_data={})


def normalize_cpf(value: str) -> str | None:
    """Retorna só dígitos se houver exatamente 11; senão None. Sem DV."""
    digits = re.sub(r"\D", "", value or "")
    if len(digits) == 11:
        return digits
    return None
