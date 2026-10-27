from __future__ import annotations

import logging
import time
import uuid
from typing import Iterable

from whatsapp_archive.models import ArchiveResult, NormalizedMessage
from whatsapp_archive.state import ProcessingState
from whatsapp_archive.storage import SafeArchiveStorage
from whatsapp_archive.whatsapp import RetryableWhatsAppError, WhatsAppClient, sleep_with_backoff

logger = logging.getLogger(__name__)


class ArchiveProcessor:
    def __init__(
        self,
        storage: SafeArchiveStorage,
        client: WhatsAppClient,
        state: ProcessingState | None = None,
        max_retries: int = 3,
        retry_backoff_seconds: float = 1.0,
    ) -> None:
        self.storage = storage
        self.client = client
        self.state = state or storage.state
        self.max_retries = max_retries
        self.retry_backoff_seconds = retry_backoff_seconds

    def process_message(self, message: NormalizedMessage) -> ArchiveResult:
        owner_token = f"{message.message_id}:{uuid.uuid4()}"
        claim = self.state.reserve_message(message.message_id, owner_token)
        if claim in {"stored", "duplicate"}:
            return ArchiveResult(message_id=message.message_id, status="duplicate")

        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                payload = self.client.download_media(message.media_id)
                file_path = self.storage.write_media(message, payload)
                self.state.mark_processed(message.message_id, str(file_path))
                logger.info("Archived message %s to %s", message.message_id, file_path)
                return ArchiveResult(message_id=message.message_id, status="stored", path=str(file_path))
            except RetryableWhatsAppError as exc:
                last_error = exc
                self.state.mark_failed(message.message_id, str(exc))
                if attempt >= self.max_retries:
                    logger.warning("Retry budget exhausted for %s: %s", message.message_id, exc)
                    raise
                logger.warning("Transient failure for %s on attempt %s/%s: %s", message.message_id, attempt + 1, self.max_retries + 1, exc)
                sleep_with_backoff(attempt, self.retry_backoff_seconds)
            except OSError as exc:
                last_error = exc
                self.state.mark_failed(message.message_id, str(exc))
                if attempt >= self.max_retries:
                    logger.warning("Disk write failed for %s: %s", message.message_id, exc)
                    raise
                logger.warning("Temporary disk error for %s on attempt %s/%s: %s", message.message_id, attempt + 1, self.max_retries + 1, exc)
                time.sleep(self.retry_backoff_seconds * (2**attempt))
            except Exception as exc:
                self.state.mark_failed(message.message_id, str(exc))
                logger.exception("Unexpected failure while processing %s", message.message_id)
                raise

        if last_error is not None:
            raise last_error
        raise RuntimeError(f"Unable to process message {message.message_id}")

    def process_messages(self, messages: Iterable[NormalizedMessage]) -> list[ArchiveResult]:
        results: list[ArchiveResult] = []
        for message in messages:
            results.append(self.process_message(message))
        return results
