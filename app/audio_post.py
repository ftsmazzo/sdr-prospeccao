"""Pós-processamento de áudio para nota de voz WhatsApp (OGG/Opus)."""

from __future__ import annotations

import logging
import random
import shutil
import subprocess
import tempfile
from pathlib import Path

logger = logging.getLogger("edu.audio_post")


def to_whatsapp_voice(mp3_bytes: bytes) -> tuple[bytes, str]:
    """
    Converte MP3 → OGG Opus mono 48 kHz ~32 kbps com filtro telefônico e silêncios.
    Retorna (bytes, formato) onde formato é "ogg" ou "mp3" (fallback).
    """
    if not mp3_bytes:
        return mp3_bytes, "mp3"
    if not shutil.which("ffmpeg"):
        logger.warning("ffmpeg ausente; enviando MP3 original")
        return mp3_bytes, "mp3"

    lead_ms = random.randint(300, 500)
    try:
        with tempfile.TemporaryDirectory(prefix="edu-voice-") as tmp:
            inp = Path(tmp) / "in.mp3"
            out = Path(tmp) / "out.ogg"
            inp.write_bytes(mp3_bytes)
            af = (
                f"highpass=f=100,lowpass=f=7000,"
                f"adelay={lead_ms}|{lead_ms},"
                f"apad=pad_dur=0.3,"
                f"loudnorm=I=-16:TP=-1.5:LRA=11"
            )
            cmd = [
                "ffmpeg",
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                str(inp),
                "-af",
                af,
                "-ac",
                "1",
                "-ar",
                "48000",
                "-c:a",
                "libopus",
                "-b:a",
                "32k",
                "-application",
                "voip",
                str(out),
            ]
            subprocess.run(cmd, check=True, capture_output=True, timeout=60)
            data = out.read_bytes()
            if len(data) < 64:
                raise RuntimeError("ogg vazio")
            return data, "ogg"
    except Exception:
        logger.exception("ffmpeg falhou; enviando MP3 original")
        return mp3_bytes, "mp3"
