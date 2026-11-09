"""Mocks de Evolution e FollowUpScheduler para simulação."""

from __future__ import annotations

from typing import Any


class MockEvolution:
    def __init__(self) -> None:
        self.outbound: list[dict[str, Any]] = []

    def drain_texts(self) -> str:
        texts = [
            str(m.get("text") or "").strip()
            for m in self.outbound
            if m.get("kind") == "text" and (m.get("text") or "").strip()
        ]
        self.outbound.clear()
        return "\n".join(texts).strip()

    async def mark_as_read(self, **kwargs: Any) -> None:
        self.outbound.append({"kind": "mark_read", **kwargs})

    async def send_presence(self, phone: str, delay_ms: int = 0, *, presence: str = "composing") -> None:
        self.outbound.append(
            {"kind": "presence", "phone": phone, "presence": presence, "delay_ms": delay_ms}
        )

    async def send_text(self, phone: str, text: str, delay_ms: int = 0) -> dict:
        self.outbound.append({"kind": "text", "phone": phone, "text": text, "delay_ms": delay_ms})
        return {"ok": True, "sim": True}

    async def send_audio(
        self,
        phone: str,
        audio_bytes: bytes,
        delay_ms: int = 0,
        *,
        encoding: bool | None = None,
    ) -> dict:
        self.outbound.append(
            {
                "kind": "audio",
                "phone": phone,
                "bytes": len(audio_bytes or b""),
                "encoding": encoding,
                "delay_ms": delay_ms,
            }
        )
        return {"ok": True, "sim": True}

    async def send_document(
        self,
        phone: str,
        file_bytes: bytes,
        *,
        filename: str,
        caption: str = "",
        mimetype: str = "application/pdf",
        delay_ms: int = 0,
    ) -> dict:
        self.outbound.append(
            {
                "kind": "document",
                "phone": phone,
                "filename": filename,
                "text": caption,
                "mimetype": mimetype,
                "bytes": len(file_bytes or b""),
                "delay_ms": delay_ms,
            }
        )
        return {"ok": True, "sim": True}

    async def download_media(self, message_payload: dict[str, Any]) -> bytes:
        return b""


class MockScheduler:
    def __init__(self) -> None:
        self.jobs: list[dict[str, Any]] = []
        self.log: list[str] = []

    def schedule_document(self, **kwargs: Any) -> dict[str, Any]:
        job = {"type": "send_contrato", **kwargs}
        self.jobs.append(job)
        msg = (
            f"[sim] FOLLOWUP_DOC seria agendado phone={kwargs.get('phone')} "
            f"course={kwargs.get('course')}"
        )
        self.log.append(msg)
        return job

    def clear_for_phone(self, phone: str) -> int:
        before = len(self.jobs)
        self.jobs = [j for j in self.jobs if j.get("phone") != phone]
        return before - len(self.jobs)

    def list_pending(self) -> list[dict[str, Any]]:
        return list(self.jobs)

    def drain_jobs_since(self, n: int) -> list[dict[str, Any]]:
        new = self.jobs[n:]
        return new
