from __future__ import annotations

import json
import logging
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

from whatsapp_archive.archive import ArchiveProcessor
from whatsapp_archive.config import AppConfig
from whatsapp_archive.state import ProcessingState
from whatsapp_archive.storage import SafeArchiveStorage
from whatsapp_archive.whatsapp import WhatsAppClient

logger = logging.getLogger(__name__)


class ArchiveRequestHandler(BaseHTTPRequestHandler):
    server_version = "WhatsAppArchive/0.1"

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/health":
            self._send_json({"status": "ok", "service": "whatsapp-archive"})
            return
        if parsed.path == "/webhook":
            params = parse_qs(parsed.query)
            mode = params.get("hub.mode", [""])[0]
            verify_token = params.get("hub.verify_token", [""])[0]
            challenge = params.get("hub.challenge", [""])[0]
            expected = self.server.config.webhook_verify_token
            if mode == "subscribe" and verify_token == expected:
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.end_headers()
                self.wfile.write(challenge.encode("utf-8"))
                return
            self._send_json({"error": "verification failed"}, status=403)
            return
        self._send_json({"error": "not found"}, status=404)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path != "/webhook":
            self._send_json({"error": "not found"}, status=404)
            return

        content_length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(content_length)
        signature = self.headers.get("X-Hub-Signature-256")
        if self.server.config.webhook_secret:
            if not WhatsAppClient.verify_signature(self.server.config.webhook_secret, raw, signature):
                self._send_json({"error": "invalid webhook signature"}, status=403)
                return

        try:
            payload = json.loads(raw.decode("utf-8"))
        except (TypeError, ValueError):
            self._send_json({"error": "invalid JSON payload"}, status=400)
            return

        messages = self.server.client.normalize_event_payload(payload)
        if not messages:
            self._send_json({"status": "accepted", "processed": 0})
            return

        results = self.server.processor.process_messages(messages)
        accepted = [result for result in results if result.status in {"stored", "duplicate"}]
        self._send_json({"status": "accepted", "processed": len(accepted), "items": [result.__dict__ for result in results]})

    def log_message(self, format: str, *args: Any) -> None:
        logger.info("%s - - [%s] %s", self.address_string(), self.log_date_time_string(), format % args)

    def _send_json(self, payload: dict[str, Any], status: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class ArchiveHTTPServer(ThreadingHTTPServer):
    daemon_threads = False
    block_on_close = True

    def __init__(self, server_address: tuple[str, int], handler_class, config: AppConfig, processor: ArchiveProcessor, client: WhatsAppClient):
        self.config = config
        self.processor = processor
        self.client = client
        super().__init__(server_address, handler_class)


def create_server(config: AppConfig | None = None) -> ArchiveHTTPServer:
    config = config or AppConfig.from_env()
    state = ProcessingState(config.state_dir or (config.archive_root / ".state"))
    state.recover_stale_processing()
    storage = SafeArchiveStorage(config.archive_root, state)
    client = WhatsAppClient(config)
    processor = ArchiveProcessor(storage, client, state=state, max_retries=config.max_retries, retry_backoff_seconds=config.retry_backoff_seconds)
    return ArchiveHTTPServer((config.listen_host, config.listen_port), ArchiveRequestHandler, config, processor, client)


def run_server(config: AppConfig | None = None) -> None:
    server = create_server(config)
    logger.info("Listening on %s:%s", server.config.listen_host, server.server_address[1])
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Shutdown requested")
    finally:
        server.server_close()
