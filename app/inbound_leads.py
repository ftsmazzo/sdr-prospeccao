"""Intake de leads (formulário, API, CSV)."""

from __future__ import annotations

import csv
import io
import logging
import re
import time
from typing import Any

from app.compra_atual import ensure_compra_atual
from app.config import Settings
from app.lead_state import ensure_lead_state
from app.memory import ConversationMemory

logger = logging.getLogger("edu.inbound_leads")

_ORIGENS = frozenset({"formulario", "anuncio", "site", "importacao"})


def normalize_whatsapp(raw: str) -> str | None:
    digits = re.sub(r"\D", "", raw or "")
    if len(digits) < 10:
        return None
    if len(digits) == 10 or len(digits) == 11:
        digits = "55" + digits
    if not digits.startswith("55") or len(digits) < 12:
        return None
    return digits


def validate_lead_payload(body: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    nome = str(body.get("nome") or "").strip()
    telefone = normalize_whatsapp(str(body.get("telefone") or body.get("whatsapp") or ""))
    origem = str(body.get("origem") or "formulario").strip().casefold()
    interesse = str(body.get("interesse") or body.get("area") or "").strip()
    graduacao = str(body.get("graduacao") or "").strip().casefold() or None
    consent = body.get("consentimento")
    consent_ok = consent in (True, "true", "1", "on", "sim", "yes")

    if not nome or len(nome) < 2:
        return None, "nome_invalido"
    if not telefone:
        return None, "telefone_invalido"
    if origem not in _ORIGENS:
        return None, "origem_invalida"
    if not consent_ok:
        return None, "consentimento_obrigatorio"
    if graduacao and graduacao not in ("concluida", "cursando", "nao_tem", "sim", "nao"):
        # aceita sim/nao do form
        if graduacao in ("sim", "já", "ja"):
            graduacao = "concluida"
        elif graduacao in ("nao", "não"):
            graduacao = "nao_tem"
        else:
            graduacao = None
    if graduacao == "sim":
        graduacao = "concluida"

    return {
        "nome": nome,
        "telefone": telefone,
        "origem": origem,
        "interesse": interesse or None,
        "graduacao": graduacao,
        "consentimento": True,
    }, None


def create_or_update_lead(
    settings: Settings,
    payload: dict[str, Any],
    *,
    schedule_first_contact: bool = True,
    stagger_seconds: float = 45,
) -> dict[str, Any]:
    phone = payload["telefone"]
    mem = ConversationMemory(settings)
    meta = mem.get_meta(phone)
    ls = ensure_lead_state(meta)

    meta["opt_out"] = False
    meta["consentimento"] = True
    meta["origem"] = payload["origem"]
    meta["interesse"] = payload.get("interesse")
    meta["lead_created_at"] = meta.get("lead_created_at") or time.time()
    meta["etapa"] = "primeiro_contato"
    ls["nome"] = payload["nome"]
    if payload.get("interesse"):
        interesse = str(payload["interesse"]).strip()
        ls["area_interesse"] = interesse
        # Se escolheu curso do catálogo, já ancora a recomendação.
        try:
            from app.course_facts import resolve_catalog_name

            canonical = resolve_catalog_name(interesse)
            if canonical:
                ls["curso_recomendado"] = canonical
                if not ls.get("curso_escolhido"):
                    ls["curso_escolhido"] = canonical
        except Exception:  # noqa: BLE001
            pass
    if payload.get("graduacao"):
        ls["graduacao"] = payload["graduacao"]
    meta["lead_state"] = ls
    meta["full_name"] = payload["nome"]
    ca = ensure_compra_atual(meta)
    ca["interesse_aluno"] = payload.get("interesse")
    ca["graduacao_aluno"] = payload.get("graduacao")
    ca["etapa"] = "primeiro_contato"
    meta["compra_atual"] = ca

    if schedule_first_contact and not meta.get("opt_out"):
        from app.followups import get_scheduler
        from app.outbound_cadence import schedule_primeiro_contato

        schedule_primeiro_contato(
            phone, meta, get_scheduler(), delay_seconds=stagger_seconds
        )

    mem.set_meta(phone, meta)
    logger.info(
        "lead criado phone=%s origem=%s interesse=%s",
        phone,
        payload["origem"],
        payload.get("interesse"),
    )
    return {"ok": True, "phone": phone, "etapa": meta["etapa"]}


def import_leads_csv(
    settings: Settings,
    content: str | bytes,
    *,
    base_stagger_seconds: float = 45,
    gap_seconds: float = 60,
) -> dict[str, Any]:
    if isinstance(content, bytes):
        content = content.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(content))
    created = 0
    errors: list[dict[str, str]] = []
    for i, row in enumerate(reader):
        raw = {
            "nome": row.get("nome") or row.get("name") or "",
            "telefone": row.get("telefone") or row.get("whatsapp") or row.get("phone") or "",
            "origem": row.get("origem") or "importacao",
            "interesse": row.get("interesse") or row.get("curso") or row.get("area") or "",
            "graduacao": row.get("graduacao") or "",
            "consentimento": row.get("consentimento") or row.get("consent") or "sim",
        }
        payload, err = validate_lead_payload(raw)
        if err or not payload:
            errors.append({"row": str(i + 2), "error": err or "invalido"})
            continue
        stagger = base_stagger_seconds + created * gap_seconds
        create_or_update_lead(
            settings, payload, schedule_first_contact=True, stagger_seconds=stagger
        )
        created += 1
    return {"ok": True, "created": created, "errors": errors}
