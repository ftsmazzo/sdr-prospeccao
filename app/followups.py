"""Agenda e dispara follow-ups: contrato com dados → depois link de checkout."""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from typing import Any

from app.checkout import create_checkout
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

    def list_pending(self) -> list[dict[str, Any]]:
        jobs: list[dict[str, Any]] = []
        if self._redis:
            for raw in self._redis.zrange(REDIS_KEY, 0, -1):
                try:
                    jobs.append(json.loads(raw))
                except json.JSONDecodeError:
                    continue
            return jobs
        return list(self._local)

    def clear_for_phone(self, phone: str) -> int:
        """Remove follow-ups pendentes de um telefone."""
        removed = 0
        if self._redis:
            raw_items = self._redis.zrange(REDIS_KEY, 0, -1)
            for raw in raw_items:
                try:
                    job = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if job.get("phone") == phone:
                    removed += int(self._redis.zrem(REDIS_KEY, raw))
        keep = []
        for job in self._local:
            if job.get("phone") == phone:
                removed += 1
            else:
                keep.append(job)
        self._local = keep
        return removed

    def clear_all(self) -> int:
        removed = 0
        if self._redis:
            removed += int(self._redis.delete(REDIS_KEY) or 0)
        removed += len(self._local)
        self._local.clear()
        return removed

    def schedule_document(
        self,
        *,
        phone: str,
        lead_name: str = "",
        cpf: str = "",
        birth_date: str = "",
        course: str = "Pós-Graduação EAD Faveni",
        delay_seconds: int | None = None,
        with_checkout: bool = True,
    ) -> dict[str, Any]:
        # Evita PDF duplicado se o modelo emitir FOLLOWUP_DOC duas vezes
        removed = self.clear_for_phone(phone)
        if removed:
            logger.info("follow-ups anteriores removidos phone=%s n=%s", phone, removed)

        delay = delay_seconds if delay_seconds is not None else self.settings.followup_delay_seconds
        job = {
            "id": str(uuid.uuid4()),
            "type": "send_contrato",
            "phone": phone,
            "lead_name": lead_name,
            "cpf": cpf,
            "birth_date": birth_date,
            "course": course,
            "with_checkout": with_checkout,
            "run_at": time.time() + max(30, delay),
            "created_at": time.time(),
        }
        if self._redis:
            self._redis.zadd(REDIS_KEY, {json.dumps(job, ensure_ascii=False): job["run_at"]})
        else:
            self._local.append(job)
        logger.info(
            "follow-up agendado id=%s phone=%s em %ss checkout=%s",
            job["id"],
            phone,
            delay,
            with_checkout,
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
        name = (job.get("lead_name") or "").strip()
        cpf = (job.get("cpf") or "").strip()
        birth = (job.get("birth_date") or "").strip()
        course = job.get("course") or "Pós-Graduação EAD Faveni"
        first = name.split()[0] if name else "oi"

        pdf = build_contrato_pdf(
            lead_name=name,
            cpf=cpf,
            birth_date=birth,
            course=course,
        )
        caption = (
            f"{first}, como combinei: segue o informativo/contrato demonstrativo "
            f"já com seus dados para {course}."
        )
        await evo.send_document(
            phone,
            pdf,
            filename="contrato-matricula-demo.pdf",
            caption=caption,
            delay_ms=2500,
        )

        if job.get("with_checkout", True):
            session = create_checkout(phone, course_label=course, lead_name=name)
            link = f"{self.settings.public_base_url.rstrip('/')}/checkout/{session.token}"
            await evo.send_text(
                phone,
                (
                    f"Se estiver tudo certo no contrato, aqui está o link para confirmar "
                    f"a matrícula (demonstração):\n{link}\n\n"
                    "Os documentos (RG, diploma etc.) podem ficar para depois — "
                    "na confirmação a gente já deixa isso combinado."
                ),
                delay_ms=3200,
            )
        else:
            await evo.send_text(
                phone,
                "Quando estiver de acordo com o contrato, me avisa que eu te mando o link da matrícula.",
                delay_ms=2800,
            )
        # Libera caminho de checkout futuro e marca contrato entregue
        try:
            from app.memory import ConversationMemory

            mem = ConversationMemory(self.settings)
            meta = mem.get_meta(phone)
            meta["pending_contract"] = False
            meta["contract_sent"] = True
            mem.set_meta(phone, meta)
        except Exception:  # noqa: BLE001
            logger.warning("não atualizou meta pós-contrato phone=%s", phone)

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
