"""Debounce + lock por telefone para inbound WhatsApp."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Awaitable, Callable

from app.config import Settings, get_settings

logger = logging.getLogger("edu.inbound_buffer")

LUA_DRAIN = """
local items = redis.call('LRANGE', KEYS[1], 0, -1)
redis.call('DEL', KEYS[1])
redis.call('DEL', KEYS[2])
return items
"""


class InboundBuffer:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.debounce_s = float(settings.inbound_debounce_seconds)
        self._redis: Any = None
        self._local_queues: dict[str, list[dict[str, Any]]] = {}
        self._local_due: dict[str, float] = {}
        self._local_locks: dict[str, float] = {}
        if settings.redis_url:
            try:
                import redis

                self._redis = redis.Redis.from_url(settings.redis_url, decode_responses=True)
                self._redis.ping()
            except Exception as exc:  # noqa: BLE001
                logger.warning("Redis indisponível para debounce: %s", exc)
                self._redis = None

    def _qkey(self, phone: str) -> str:
        return f"edu:debounce:{phone}"

    def _duekey(self, phone: str) -> str:
        return f"edu:debounce:due:{phone}"

    def _lockkey(self, phone: str) -> str:
        return f"edu:lock:{phone}"

    def enqueue(self, item: dict[str, Any]) -> None:
        phone = item["phone"]
        due_at = time.time() + self.debounce_s
        payload = json.dumps(item, ensure_ascii=False)
        if self._redis:
            pipe = self._redis.pipeline()
            pipe.rpush(self._qkey(phone), payload)
            pipe.set(self._duekey(phone), str(due_at))
            pipe.execute()
            return
        self._local_queues.setdefault(phone, []).append(item)
        self._local_due[phone] = due_at

    def due_phones(self) -> list[str]:
        now = time.time()
        phones: list[str] = []
        if self._redis:
            for key in self._redis.keys("edu:debounce:due:*"):
                phone = key.rsplit(":", 1)[-1]
                raw = self._redis.get(key)
                try:
                    due = float(raw or 0)
                except ValueError:
                    due = 0
                if due <= now:
                    phones.append(phone)
            return phones
        for phone, due in list(self._local_due.items()):
            if due <= now:
                phones.append(phone)
        return phones

    def drain(self, phone: str) -> list[dict[str, Any]]:
        if self._redis:
            try:
                raw_items = self._redis.eval(LUA_DRAIN, 2, self._qkey(phone), self._duekey(phone))
            except Exception:  # noqa: BLE001
                pipe = self._redis.pipeline()
                pipe.lrange(self._qkey(phone), 0, -1)
                pipe.delete(self._qkey(phone))
                pipe.delete(self._duekey(phone))
                results = pipe.execute()
                raw_items = results[0] or []
            out: list[dict[str, Any]] = []
            for raw in raw_items:
                try:
                    out.append(json.loads(raw))
                except json.JSONDecodeError:
                    continue
            return out

        items = self._local_queues.pop(phone, [])
        self._local_due.pop(phone, None)
        return items

    def try_lock(self, phone: str, ttl: int = 120) -> bool:
        if self._redis:
            return bool(self._redis.set(self._lockkey(phone), "1", nx=True, ex=ttl))
        now = time.time()
        exp = self._local_locks.get(phone, 0)
        if exp > now:
            return False
        self._local_locks[phone] = now + ttl
        return True

    def unlock(self, phone: str) -> None:
        if self._redis:
            self._redis.delete(self._lockkey(phone))
            return
        self._local_locks.pop(phone, None)


_buffer: InboundBuffer | None = None


def get_inbound_buffer() -> InboundBuffer:
    global _buffer
    if _buffer is None:
        _buffer = InboundBuffer(get_settings())
    return _buffer


ProcessBatchFn = Callable[[str, list[dict[str, Any]]], Awaitable[None]]


async def inbound_worker(stop_event: asyncio.Event, process_batch: ProcessBatchFn) -> None:
    """Dispara um create_task por telefone; lock na tarefa; aguarda tasks no shutdown."""
    buf = get_inbound_buffer()
    running: set[asyncio.Task] = set()
    logger.info("inbound debounce worker iniciado")

    def _task_done(task: asyncio.Task) -> None:
        running.discard(task)
        if not task.cancelled() and task.exception():
            logger.error("lote inbound falhou: %s", task.exception())

    async def _run_phone(phone: str) -> None:
        try:
            batch = buf.drain(phone)
            if batch:
                await process_batch(phone, batch)
        finally:
            buf.unlock(phone)

    while not stop_event.is_set():
        try:
            for phone in buf.due_phones():
                if not buf.try_lock(phone):
                    continue
                task = asyncio.create_task(_run_phone(phone), name=f"inbound-{phone}")
                running.add(task)
                task.add_done_callback(_task_done)
        except Exception:
            logger.exception("erro no inbound worker")
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=1.0)
        except asyncio.TimeoutError:
            pass

    if running:
        logger.info("aguardando %s lotes inbound no shutdown", len(running))
        await asyncio.gather(*running, return_exceptions=True)
