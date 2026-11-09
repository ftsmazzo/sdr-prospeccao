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
    doc = message.get("documentMessage") or {}
    if doc.get("caption"):
        return str(doc["caption"]).strip()
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
    has_image = "imageMessage" in message
    has_document = "documentMessage" in message

    if not text and not has_audio and not has_image and not has_document:
        return None

    phone = remote.split("@")[0]
    media_message = None
    if has_audio or has_image or has_document:
        media_message = {
            "key": key,
            "message": message,
        }

    doc = message.get("documentMessage") or {}
    filename = str(doc.get("fileName") or doc.get("title") or "").strip()

    return {
        "phone": phone,
        "remote_jid": remote,
        "push_name": data.get("pushName") or "",
        "text": text or "",
        "has_audio": has_audio,
        "has_image": has_image,
        "has_document": has_document,
        "document_filename": filename,
        "message_id": key.get("id"),
        "media_message": media_message,
        "raw_data": data,
    }
