"""Regras de envio ativo (janela, limite diário, opt-out, LGPD)."""

from __future__ import annotations

import logging
import random
import re
import time
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from app.config import Settings
from app.notify import is_internal_number, parse_notify_numbers

logger = logging.getLogger("edu.active_send")

TZ = ZoneInfo("America/Sao_Paulo")
REDIS_DAILY_KEY = "edu:active_send:daily:{date}"


def now_brasilia(now_ts: float | None = None) -> datetime:
    if now_ts is None:
        return datetime.now(TZ)
    return datetime.fromtimestamp(now_ts, tz=TZ)


def within_active_window(now_ts: float | None = None) -> bool:
    """Seg–sáb, 8h–20h (Brasília)."""
    dt = now_brasilia(now_ts)
    if dt.weekday() >= 6:  # domingo = 6
        return False
    return 8 <= dt.hour < 20


def next_window_start(now_ts: float | None = None) -> float:
    """Próximo instante válido para envio ativo (epoch)."""
    dt = now_brasilia(now_ts)
    # Se dentro da janela, agora.
    if within_active_window(now_ts):
        return dt.timestamp()
    # Avança até próxima 8h em dia útil.
    candidate = dt.replace(hour=8, minute=0, second=0, microsecond=0)
    if dt.hour >= 20 or not within_active_window(now_ts):
        from datetime import timedelta

        candidate = candidate + timedelta(days=1)
        while candidate.weekday() >= 6:
            candidate = candidate + timedelta(days=1)
        # Se ainda é o mesmo dia mas antes das 8h
        if dt.hour < 8 and dt.weekday() < 6:
            candidate = dt.replace(hour=8, minute=0, second=0, microsecond=0)
    return candidate.timestamp()


def normalize_phone(phone: str) -> str:
    return re.sub(r"\D", "", phone or "")


def can_send_active(
    meta: dict[str, Any],
    phone: str,
    settings: Settings,
) -> tuple[bool, str]:
    if meta.get("opt_out"):
        return False, "opt_out"
    if meta.get("retomadas_paused"):
        return False, "paused"
    if not meta.get("consentimento"):
        # Leads inbound orgânicos (WhatsApp) têm consentimento implícito de conversa;
        # envio ATIVO (primeiro contato / retomada iniciada por nós) exige flag.
        if meta.get("origem") in ("formulario", "anuncio", "site", "importacao"):
            return False, "sem_consentimento"
    ls = meta.get("lead_state") or {}
    if ls.get("e_aluno_atual") or meta.get("etapa") == "aluno_atual":
        return False, "aluno_atual"
    nums = parse_notify_numbers(settings.handoff_notify_numbers)
    if is_internal_number(phone, nums):
        return False, "interno"
    return True, "ok"


def _daily_count(redis: Any, day: str) -> int:
    if not redis:
        return 0
    try:
        return int(redis.get(REDIS_DAILY_KEY.format(date=day)) or 0)
    except Exception:  # noqa: BLE001
        return 0


def _incr_daily(redis: Any, day: str) -> int:
    if not redis:
        return 1
    key = REDIS_DAILY_KEY.format(date=day)
    n = int(redis.incr(key))
    redis.expire(key, 60 * 60 * 36)
    return n


def random_batch_delay_seconds(settings: Settings) -> float:
    lo = max(1, int(getattr(settings, "active_send_min_gap_seconds", 30) or 30))
    hi = max(lo, int(getattr(settings, "active_send_max_gap_seconds", 120) or 120))
    return float(random.randint(lo, hi))


async def dispatch_active_job(
    evo: Any,
    settings: Settings,
    job: dict[str, Any],
    *,
    scheduler: Any,
) -> None:
    """Envia primeiro_contato / retomada respeitando janela e limite."""
    phone = normalize_phone(str(job.get("phone") or ""))
    if not phone:
        return

    from app.memory import ConversationMemory

    mem = ConversationMemory(settings)
    meta = mem.get_meta(phone)
    ok, reason = can_send_active(meta, phone, settings)
    if not ok:
        logger.info("active_send bloqueado phone=%s reason=%s", phone, reason)
        return

    now = time.time()
    if not within_active_window(now):
        # Reagenda para a próxima janela.
        run_at = next_window_start(now)
        scheduler.schedule_job(
            phone=phone,
            job_type=str(job.get("type") or "retomada"),
            run_at=run_at,
            payload={k: v for k, v in job.items() if k not in ("id", "run_at", "created_at")},
        )
        logger.info("active_send fora da janela — reagendado phone=%s", phone)
        return

    redis = getattr(scheduler, "_redis", None)
    day = now_brasilia(now).strftime("%Y-%m-%d")
    limit = int(getattr(settings, "active_send_daily_limit", 50) or 50)
    if _daily_count(redis, day) >= limit:
        # Empurra para amanhã 8h.
        run_at = next_window_start(now + 16 * 3600)
        scheduler.schedule_job(
            phone=phone,
            job_type=str(job.get("type") or "retomada"),
            run_at=run_at,
            payload={k: v for k, v in job.items() if k not in ("id", "run_at", "created_at")},
        )
        logger.info("active_send limite diário — reagendado phone=%s", phone)
        return

    text = str(job.get("text") or "").strip()
    jtype = str(job.get("type") or "")
    if not text and jtype in ("primeiro_contato", "retomada"):
        from app.outbound_cadence import compose_active_message

        text = await compose_active_message(settings, phone, meta, job)

    if not text:
        logger.warning("active_send sem texto phone=%s type=%s", phone, jtype)
        return

    # Intervalo humano entre envios do lote.
    delay_ms = int(random_batch_delay_seconds(settings) * 1000)
    await evo.send_text(phone, text, delay_ms=min(delay_ms, 8000))
    _incr_daily(redis, day)

    mem.append(phone, "assistant", text)
    hist = list(meta.get("active_sends") or [])
    hist.append(
        {
            "at": datetime.now(TZ).isoformat(),
            "trigger": job.get("trigger") or jtype,
            "text": text[:500],
        }
    )
    meta["active_sends"] = hist[-30:]
    meta["last_active_send_at"] = time.time()
    # Atualiza ponteiro da cadência
    if jtype == "retomada":
        meta["retomada_step"] = int(meta.get("retomada_step") or 0) + 1
    mem.set_meta(phone, meta)
    logger.info("active_send ok phone=%s type=%s", phone, jtype)
