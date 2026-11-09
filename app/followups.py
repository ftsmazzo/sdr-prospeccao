"""Agenda e dispara follow-ups prometidos (ex.: enviar contrato em 15 min)."""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from typing import Any

from app.clients.evolution import EvolutionClient
from app.config import Settings, get_settings
from app.documents import build_contrato_pdf

logger = logging.getLogger("edu.followups")

REDIS_KEY = "edu:followups"


class FollowUpScheduler:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._local: list[dict[str, Any]] = []
        self._redis: Any = None
        if settings.redis_url:
            try:
                import redis

                self._redis = redis.Redis.from_url(settings.redis_url, decode_responses=True)
                self._redis.ping()
            except Exception as exc:  # noqa: BLE001
                logger.warning("Redis indisponível para follow-ups: %s", exc)
                self._redis = None

    def schedule_document(
        self,
        *,
        phone: str,
        lead_name: str = "",
        course: str = "Pós-Graduação EAD Faveni",
        delay_seconds: int | None = None,
    ) -> dict[str, Any]:
        delay = delay_seconds if delay_seconds is not None else self.settings.followup_delay_seconds
        job = {
            "id": str(uuid.uuid4()),
            "type": "send_contrato",
            "phone": phone,
            "lead_name": lead_name,
            "course": course,
            "run_at": time.time() + max(30, delay),
            "created_at": time.time(),
        }
        if self._redis:
            self._redis.zadd(REDIS_KEY, {json.dumps(job, ensure_ascii=False): job["run_at"]})
        else:
            self._local.append(job)
        logger.info(
            "follow-up agendado id=%s phone=%s em %ss",
            job["id"],
            phone,
            delay,
        )
        return job

    def _due_jobs(self) -> list[dict[str, Any]]:
        now = time.time()
        due: list[dict[str, Any]] = []
        if self._redis:
            raw_items = self._redis.zrangebyscore(REDIS_KEY, 0, now)
            for raw in raw_items:
                try:
                    due.append(json.loads(raw))
                except json.JSONDecodeError:
                    self._redis.zrem(REDIS_KEY, raw)
            if raw_items:
                self._redis.zrem(REDIS_KEY, *raw_items)
            return due

        keep = []
        for job in self._local:
            if job["run_at"] <= now:
                due.append(job)
            else:
                keep.append(job)
        self._local = keep
        return due

    async def dispatch_due(self) -> int:
        jobs = self._due_jobs()
        if not jobs:
            return 0
        evo = EvolutionClient(self.settings)
        sent = 0
        for job in jobs:
            try:
                await self._run_job(evo, job)
                sent += 1
            except Exception:
                logger.exception("falha no follow-up %s", job.get("id"))
        return sent

    async def _run_job(self, evo: EvolutionClient, job: dict[str, Any]) -> None:
        phone = job["phone"]
        name = job.get("lead_name") or ""
        course = job.get("course") or "Pós-Graduação EAD Faveni"
        first = name.split()[0] if name.strip() else "oi"

        pdf = build_contrato_pdf(lead_name=name, course=course)
        caption = (
            f"{first}, como combinei: segue o informativo/contrato demonstrativo da matrícula "
            f"em {course}. É um documento de demonstração — qualquer ajuste a gente resolve por aqui."
        )
        await evo.send_document(
            phone,
            pdf,
            filename="contrato-matricula-demo.pdf",
            caption=caption,
            delay_ms=2500,
        )
        await evo.send_text(
            phone,
            "Quando você tiver os documentos em mãos, me avisa que eu te guio no próximo passo da matrícula "
            "(na demo também posso te mandar o link de confirmação).",
            delay_ms=2800,
        )
        logger.info("follow-up enviado phone=%s job=%s", phone, job.get("id"))


_scheduler: FollowUpScheduler | None = None


def get_scheduler() -> FollowUpScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = FollowUpScheduler(get_settings())
    return _scheduler


async def followup_worker(stop_event: asyncio.Event) -> None:
    scheduler = get_scheduler()
    logger.info("follow-up worker iniciado")
    while not stop_event.is_set():
        try:
            n = await scheduler.dispatch_due()
            if n:
                logger.info("follow-ups disparados: %s", n)
        except Exception:
            logger.exception("erro no worker de follow-up")
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=20)
        except asyncio.TimeoutError:
            pass
