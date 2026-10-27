from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from whatsapp_archive.config import SUPPORTED_EXTENSIONS


@dataclass(frozen=True)
class NormalizedMessage:
    message_id: str
    media_id: str
    filename: str
    mime_type: str
    source: str
    timestamp: str
    extension: str
    raw_message: dict = field(default_factory=dict)

    @property
    def file_type(self) -> str:
        return self.extension.lower().lstrip(".")

    @classmethod
    def from_webhook_message(cls, message: dict) -> "NormalizedMessage | None":
        if not isinstance(message, dict):
            return None

        message_id = str(message.get("id") or message.get("message_id") or "").strip()
        if not message_id:
            return None

        kind = None
        payload = None
        if "document" in message:
            kind = "document"
            payload = message.get("document", {})
        elif "image" in message:
            kind = "image"
            payload = message.get("image", {})
        elif "audio" in message:
            kind = "audio"
            payload = message.get("audio", {})
        elif "sticker" in message:
            kind = "sticker"
            payload = message.get("sticker", {})

        if kind is None or not isinstance(payload, dict):
            return None

        filename = str(payload.get("filename") or message.get("caption") or "").strip()
        if not filename and kind in {"document", "image"}:
            filename = f"{message_id}.pdf" if kind == "document" else f"{message_id}.jpg"

        extension = Path(filename).suffix.lower()
        if extension not in SUPPORTED_EXTENSIONS:
            return None

        media_id = str(payload.get("media_id") or payload.get("id") or message.get("media", {}).get("id") or "").strip()
        if not media_id:
            media_id = str(message.get("image", {}).get("id") or message.get("document", {}).get("id") or "").strip()
        if not media_id:
            return None

        mime_type = str(payload.get("mime_type") or payload.get("mimetype") or "application/octet-stream").strip()
        return cls(
            message_id=message_id,
            media_id=media_id,
            filename=filename,
            mime_type=mime_type,
            source=kind,
            timestamp=str(message.get("timestamp") or ""),
            extension=extension,
            raw_message=message,
        )


@dataclass(frozen=True)
class ArchiveResult:
    message_id: str
    status: str
    path: str | None = None
    warning: str | None = None
