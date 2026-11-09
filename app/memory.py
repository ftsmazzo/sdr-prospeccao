import json
import logging
from typing import Any

import redis

from app.config import Settings

logger = logging.getLogger("edu.memory")


class ConversationMemory:
    """Histórico curto por telefone. Usa Redis se disponível; senão memória de processo."""

    def __init__(self, settings: Settings):
        self._local: dict[str, list[dict[str, str]]] = {}
        self._redis: redis.Redis | None = None
        if settings.redis_url:
            try:
                self._redis = redis.Redis.from_url(settings.redis_url, decode_responses=True)
                self._redis.ping()
            except Exception as exc:  # noqa: BLE001
                logger.warning("Redis indisponível, usando memória local: %s", exc)
                self._redis = None

    def _key(self, phone: str) -> str:
        return f"edu:conv:{phone}"

    def get_history(self, phone: str) -> list[dict[str, str]]:
        if self._redis:
            raw = self._redis.get(self._key(phone))
            if not raw:
                return []
            return json.loads(raw)
        return list(self._local.get(phone, []))

    def append(self, phone: str, role: str, content: str, max_turns: int = 20) -> None:
        history = self.get_history(phone)
        history.append({"role": role, "content": content})
        history = history[-max_turns:]
        if self._redis:
            self._redis.setex(self._key(phone), 60 * 60 * 24, json.dumps(history, ensure_ascii=False))
        else:
            self._local[phone] = history

    def get_meta(self, phone: str) -> dict[str, Any]:
        if self._redis:
            raw = self._redis.get(f"edu:meta:{phone}")
            return json.loads(raw) if raw else {}
        return getattr(self, "_meta", {}).get(phone, {})

    def set_meta(self, phone: str, meta: dict[str, Any]) -> None:
        if self._redis:
            self._redis.setex(f"edu:meta:{phone}", 60 * 60 * 24, json.dumps(meta, ensure_ascii=False))
            return
        if not hasattr(self, "_meta"):
            self._meta = {}
        self._meta[phone] = meta
