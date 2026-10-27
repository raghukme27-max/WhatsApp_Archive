from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
from urllib import request, error

from whatsapp_archive.config import AppConfig
from whatsapp_archive.models import NormalizedMessage

logger = logging.getLogger(__name__)


class WhatsAppClientError(RuntimeError):
    pass


class RetryableWhatsAppError(WhatsAppClientError):
    pass


class WhatsAppClient:
    def __init__(self, config: AppConfig):
        self.config = config

    def verify_subscription(self, params: dict[str, str]) -> str | None:
        mode = params.get("hub.mode")
        verify_token = params.get("hub.verify_token")
        challenge = params.get("hub.challenge")
        if mode == "subscribe" and verify_token == self.config.webhook_verify_token:
            return str(challenge or "")
        return None

    @staticmethod
    def verify_signature(secret: str, payload: bytes, provided_signature: str | None) -> bool:
        if not secret:
            return True
        if not provided_signature:
            return False
        expected = "sha256=" + hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, provided_signature.strip())

    def fetch_media_metadata(self, media_id: str) -> dict:
        if self.config.local_dev_mode:
            return {"url": f"https://example.invalid/{media_id}", "mime_type": "application/octet-stream"}

        if not self.config.access_token:
            raise WhatsAppClientError("WA_ACCESS_TOKEN is required unless local mode is enabled")

        endpoint = f"{self.config.api_base_url.rstrip('/')}/{media_id}"
        headers = {"Authorization": f"Bearer {self.config.access_token}", "Accept": "application/json"}
        req = request.Request(endpoint, headers=headers, method="GET")
        try:
            with request.urlopen(req, timeout=30) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except error.HTTPError as exc:
            raise RetryableWhatsAppError(f"Media metadata lookup failed: {exc}") from exc
        except error.URLError as exc:
            raise RetryableWhatsAppError(f"Media metadata lookup failed: {exc}") from exc

        if not isinstance(payload, dict):
            raise WhatsAppClientError("Bad media metadata response from WhatsApp")
        return payload

    def download_media(self, media_id: str) -> bytes:
        if self.config.local_dev_mode:
            logger.info("Local dev mode enabled; returning synthetic bytes for %s", media_id)
            return b"local-dev-media-content"

        metadata = self.fetch_media_metadata(media_id)
        media_url = metadata.get("url")
        if not media_url:
            raise WhatsAppClientError(f"No media URL returned for media id {media_id}")

        headers = {"Authorization": f"Bearer {self.config.access_token}", "User-Agent": "WhatsAppArchive/0.1"}
        req = request.Request(media_url, headers=headers, method="GET")
        try:
            with request.urlopen(req, timeout=30) as response:
                return response.read()
        except error.HTTPError as exc:
            raise RetryableWhatsAppError(f"Media download failed for {media_id}: {exc}") from exc
        except error.URLError as exc:
            raise RetryableWhatsAppError(f"Media download failed for {media_id}: {exc}") from exc

    @staticmethod
    def normalize_event_payload(payload: dict) -> list[NormalizedMessage]:
        messages: list[NormalizedMessage] = []
        if not isinstance(payload, dict):
            return messages

        for entry in payload.get("entry", []):
            if not isinstance(entry, dict):
                continue
            for change in entry.get("changes", []):
                if not isinstance(change, dict):
                    continue
                value = change.get("value", {})
                if not isinstance(value, dict):
                    continue
                for message in value.get("messages", []):
                    normalized = NormalizedMessage.from_webhook_message(message)
                    if normalized is not None:
                        messages.append(normalized)
        return messages


def sleep_with_backoff(attempt: int, seconds: float) -> None:
    time.sleep(seconds * (2**attempt))
