from typing import Any


def _extract_text(message: dict[str, Any]) -> str | None:
    if not message:
        return None
    if message.get("conversation"):
        return str(message["conversation"]).strip()
    ext = message.get("extendedTextMessage") or {}
    if ext.get("text"):
        return str(ext["text"]).strip()
    image = message.get("imageMessage") or {}
    if image.get("caption"):
        return str(image["caption"]).strip()
    # áudio: na fase 2 virá STT; por enquanto sinaliza
    if message.get("audioMessage"):
        return None
    return None


def parse_incoming(payload: dict[str, Any]) -> dict[str, Any] | None:
    """Normaliza webhook Evolution (MESSAGES_UPSERT) para um dict simples."""
    event = (payload.get("event") or payload.get("type") or "").lower()
    if event and "messages" not in event and "upsert" not in event:
        # ainda assim tenta se houver data.message
        pass

    data = payload.get("data") or payload
    # alguns formatos enviam lista
    if isinstance(data, list):
        if not data:
            return None
        data = data[0]

    key = data.get("key") or {}
    if key.get("fromMe") is True:
        return None

    remote = key.get("remoteJid") or data.get("remoteJid") or ""
    if not remote or remote.endswith("@g.us"):
        return None

    message = data.get("message") or {}
    # ignore reactions / protocol
    if "reactionMessage" in message or "protocolMessage" in message:
        return None

    text = _extract_text(message)
    has_audio = "audioMessage" in message

    if not text and not has_audio:
        return None

    phone = remote.split("@")[0]
    return {
        "phone": phone,
        "remote_jid": remote,
        "push_name": data.get("pushName") or "",
        "text": text or "",
        "has_audio": has_audio,
        "message_id": key.get("id"),
    }
