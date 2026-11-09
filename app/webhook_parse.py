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
    if message.get("audioMessage"):
        return None
    return None


def parse_incoming(payload: dict[str, Any]) -> dict[str, Any] | None:
    """Normaliza webhook Evolution (MESSAGES_UPSERT) para um dict simples."""
    data = payload.get("data") or payload
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
    if "reactionMessage" in message or "protocolMessage" in message:
        return None

    text = _extract_text(message)
    has_audio = "audioMessage" in message

    if not text and not has_audio:
        return None

    phone = remote.split("@")[0]
    # objeto no formato esperado por getBase64FromMediaMessage
    media_message = {
        "key": key,
        "message": message,
    }
    return {
        "phone": phone,
        "remote_jid": remote,
        "push_name": data.get("pushName") or "",
        "text": text or "",
        "has_audio": has_audio,
        "message_id": key.get("id"),
        "media_message": media_message if has_audio else None,
        "raw_data": data,
    }
