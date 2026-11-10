import json
import logging
from typing import Any

import redis

from app.config import Settings

logger = logging.getLogger("edu.memory")


class ConversationMemory:
    """Histórico curto por telefone. Usa Redis se disponível; senão memória de processo."""

    # Fallback in-process compartilhado entre instâncias (testes / Redis down).
    _shared_local: dict[str, list[dict[str, str]]] = {}
    _shared_meta: dict[str, dict] = {}

    def __init__(self, settings: Settings):
        self.settings = settings
        self._ttl = settings.memory_ttl_seconds
        self._max_messages = settings.memory_max_messages
        self._local = ConversationMemory._shared_local
        self._meta = ConversationMemory._shared_meta
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

    def append(
        self,
        phone: str,
        role: str,
        content: str,
        max_turns: int | None = None,
        *,
        source: str | None = None,
    ) -> None:
        limit = max_turns if max_turns is not None else self._max_messages
        history = self.get_history(phone)
        msg: dict[str, str] = {"role": role, "content": content}
        if source:
            msg["source"] = source
        history.append(msg)
        history = history[-limit:]
        if self._redis:
            self._redis.setex(self._key(phone), self._ttl, json.dumps(history, ensure_ascii=False))
        else:
            self._local[phone] = history

    def get_meta(self, phone: str) -> dict[str, Any]:
        if self._redis:
            raw = self._redis.get(f"edu:meta:{phone}")
            return json.loads(raw) if raw else {}
        return dict(self._meta.get(phone) or {})

    def set_meta(self, phone: str, meta: dict[str, Any]) -> None:
        if self._redis:
            self._redis.setex(
                f"edu:meta:{phone}",
                self._ttl,
                json.dumps(meta, ensure_ascii=False),
            )
            return
        self._meta[phone] = meta

    def replace_history(self, phone: str, history: list[dict[str, str]]) -> None:
        """Substitui o histórico completo (admin / rewind)."""
        trimmed = list(history)[-self._max_messages :]
        if self._redis:
            self._redis.setex(
                self._key(phone),
                self._ttl,
                json.dumps(trimmed, ensure_ascii=False),
            )
            return
        self._local[phone] = trimmed

    def clear(self, phone: str) -> bool:
        """Apaga histórico e meta de um telefone."""
        found = False
        if self._redis:
            deleted = self._redis.delete(self._key(phone), f"edu:meta:{phone}")
            found = bool(deleted)
        if phone in self._local:
            del self._local[phone]
            found = True
        if phone in self._meta:
            del self._meta[phone]
            found = True
        return found

    def clear_all(self) -> int:
        """Apaga todas as conversas Edu (conv + meta). Retorna quantidade de chaves removidas."""
        removed = 0
        if self._redis:
            keys: list[str] = []
            for pattern in ("edu:conv:*", "edu:meta:*"):
                keys.extend(self._redis.keys(pattern))
            if keys:
                removed = int(self._redis.delete(*keys))
        removed += len(self._local)
        self._local.clear()
        removed += len(self._meta)
        self._meta.clear()
        return removed
