from __future__ import annotations

import hashlib
import hmac
import json
import os
import tempfile
import threading
import unittest
from pathlib import Path

from whatsapp_archive.archive import ArchiveProcessor
from whatsapp_archive.config import AppConfig
from whatsapp_archive.models import NormalizedMessage
from whatsapp_archive.server import ArchiveHTTPServer, ArchiveRequestHandler
from whatsapp_archive.state import ProcessingState
from whatsapp_archive.storage import SafeArchiveStorage
from whatsapp_archive.whatsapp import WhatsAppClient


class FakeWhatsAppClient:
    def __init__(self):
        self.calls = []

    def download_media(self, media_id: str) -> bytes:
        self.calls.append(media_id)
        return b"hello-world-payload"


class StorageTests(unittest.TestCase):
    def test_sanitize_filename_removes_path_traversal(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            state = ProcessingState(Path(temp_dir) / ".state")
            storage = SafeArchiveStorage(Path(temp_dir) / "archive", state)
            sanitized = storage.sanitize_filename("../../etc/passwd.pdf")
            self.assertTrue(sanitized.endswith(".pdf"))
            self.assertNotIn("..", sanitized)
            self.assertEqual(Path(sanitized).name, sanitized)

    def test_write_media_uses_atomic_finalization_and_collision_protection(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            archive_root = Path(temp_dir) / "archive"
            state = ProcessingState(Path(temp_dir) / ".state")
            storage = SafeArchiveStorage(archive_root, state)
            message = NormalizedMessage(
                message_id="abc",
                media_id="media-1",
                filename="sample.pdf",
                mime_type="application/pdf",
                source="document",
                timestamp="123",
                extension=".pdf",
            )
            path1 = storage.write_media(message, b"one")
            path2 = storage.write_media(message, b"two")
            self.assertNotEqual(path1, path2)
            self.assertTrue(path1.exists())
            self.assertTrue(path2.exists())

    def test_processor_prevents_duplicate_processing(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            archive_root = Path(temp_dir) / "archive"
            state = ProcessingState(Path(temp_dir) / ".state")
            storage = SafeArchiveStorage(archive_root, state)
            client = FakeWhatsAppClient()
            processor = ArchiveProcessor(storage, client, state=state, max_retries=1, retry_backoff_seconds=0.01)
            message = NormalizedMessage(
                message_id="dup-message",
                media_id="copy-1",
                filename="notice.pdf",
                mime_type="application/pdf",
                source="document",
                timestamp="456",
                extension=".pdf",
            )
            first = processor.process_message(message)
            second = processor.process_message(message)
            self.assertEqual(first.status, "stored")
            self.assertEqual(second.status, "duplicate")
            self.assertEqual(len(client.calls), 1)

    def test_storage_rejects_dangerous_filenames(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            state = ProcessingState(Path(temp_dir) / ".state")
            storage = SafeArchiveStorage(Path(temp_dir) / "archive", state)
            for bad in [
                "../../secret.pdf",
                "..\\..\\secret.pdf",
                "C:\\Windows\\test.pdf",
                "/Users/test/test.pdf",
                "CON.pdf",
                "NUL.pdf",
                "COM1.txt",
                "LPT1.txt",
                "file?.pdf",
                "file*.pdf",
                "file:.pdf",
            ]:
                safe = storage.sanitize_filename(bad)
                self.assertTrue(Path(safe).name == safe)
                self.assertNotIn("..", safe)
                self.assertNotIn("\\", safe)
                self.assertNotIn("/", safe)


class ServerTests(unittest.TestCase):
    def test_server_waits_for_request_threads_during_shutdown(self):
        self.assertFalse(ArchiveHTTPServer.daemon_threads)
        self.assertTrue(ArchiveHTTPServer.block_on_close)

    def test_server_close_waits_for_active_request(self):
        request_started = threading.Event()
        finish_request = threading.Event()
        close_started = threading.Event()
        close_finished = threading.Event()

        class BlockingHandler:
            def __init__(self, request, client_address, server):
                self.request = request
                request_started.set()
                finish_request.wait(timeout=5)
                self.request.sendall(b"HTTP/1.0 200 OK\r\nContent-Length: 2\r\n\r\nOK")
                self.request.close()

        with tempfile.TemporaryDirectory() as temp_dir:
            config = AppConfig(archive_root=Path(temp_dir) / "archive")
            server = ArchiveHTTPServer(("127.0.0.1", 0), BlockingHandler, config, None, None)
            serving_thread = threading.Thread(target=server.serve_forever, daemon=True)
            serving_thread.start()

            def send_request():
                import urllib.request

                with urllib.request.urlopen(f"http://127.0.0.1:{server.server_port}/", timeout=5) as response:
                    response.read()

            request_thread = threading.Thread(target=send_request, daemon=True)
            request_thread.start()
            self.assertTrue(request_started.wait(timeout=2))
            server.shutdown()

            def close_server():
                close_started.set()
                server.server_close()
                close_finished.set()

            closer_thread = threading.Thread(target=close_server)
            closer_thread.start()
            try:
                self.assertTrue(close_started.wait(timeout=2))
                self.assertFalse(close_finished.wait(timeout=0.05))
            finally:
                finish_request.set()
                closer_thread.join(timeout=2)
                serving_thread.join(timeout=2)
                request_thread.join(timeout=2)
            self.assertTrue(close_finished.is_set())

    def test_subscription_verification(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = AppConfig(
                archive_root=Path(temp_dir) / "archive",
                webhook_verify_token="secret-token",
                state_dir=Path(temp_dir) / ".state",
                local_dev_mode=True,
            )
            state = ProcessingState(config.state_dir or config.archive_root / ".state")
            storage = SafeArchiveStorage(config.archive_root, state)
            client = WhatsAppClient(config)
            processor = ArchiveProcessor(storage, client, state=state, max_retries=1, retry_backoff_seconds=0.01)
            server = ArchiveHTTPServer(("127.0.0.1", 0), ArchiveRequestHandler, config, processor, client)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                import urllib.request

                url = f"http://127.0.0.1:{server.server_port}/webhook?hub.mode=subscribe&hub.verify_token=secret-token&hub.challenge=abc123"
                with urllib.request.urlopen(url, timeout=5) as response:
                    self.assertEqual(response.read().decode("utf-8"), "abc123")
            finally:
                server.shutdown()
                server.server_close()

    def test_webhook_ingests_supported_documents(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = AppConfig(
                archive_root=Path(temp_dir) / "archive",
                webhook_verify_token="secret-token",
                state_dir=Path(temp_dir) / ".state",
                local_dev_mode=True,
            )
            state = ProcessingState(config.state_dir or config.archive_root / ".state")
            storage = SafeArchiveStorage(config.archive_root, state)
            client = WhatsAppClient(config)
            processor = ArchiveProcessor(storage, client, state=state, max_retries=1, retry_backoff_seconds=0.01)
            server = ArchiveHTTPServer(("127.0.0.1", 0), ArchiveRequestHandler, config, processor, client)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                import urllib.request
                payload = {
                    "entry": [
                        {"changes": [{"value": {"messages": [{"id": "message-123", "document": {"filename": "advisory.pdf", "media_id": "media-a", "mime_type": "application/pdf"}}]}}]}
                    ]
                }
                request = urllib.request.Request(
                    f"http://127.0.0.1:{server.server_port}/webhook",
                    data=json.dumps(payload).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(request, timeout=5) as response:
                    body = json.loads(response.read().decode("utf-8"))
                    self.assertEqual(body["status"], "accepted")
                    self.assertGreaterEqual(body["processed"], 1)
                    self.assertTrue((config.archive_root).exists())
            finally:
                server.shutdown()
                server.server_close()

    def test_webhook_signature_validation(self):
        secret = "shared-secret"
        payload = b'{"hello":"world"}'
        header = "sha256=" + hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
        self.assertTrue(WhatsAppClient.verify_signature(secret, payload, header))
        self.assertFalse(WhatsAppClient.verify_signature(secret, payload, "sha256=wrong"))
        self.assertFalse(WhatsAppClient.verify_signature(secret, payload, None))

    def test_duplicate_webhook_requests_do_not_double_archive(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = AppConfig(
                archive_root=Path(temp_dir) / "archive",
                webhook_verify_token="secret-token",
                state_dir=Path(temp_dir) / ".state",
                local_dev_mode=True,
            )
            state = ProcessingState(config.state_dir or config.archive_root / ".state")
            storage = SafeArchiveStorage(config.archive_root, state)
            client = WhatsAppClient(config)
            processor = ArchiveProcessor(storage, client, state=state, max_retries=1, retry_backoff_seconds=0.01)
            server = ArchiveHTTPServer(("127.0.0.1", 0), ArchiveRequestHandler, config, processor, client)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                import urllib.request
                payload = {
                    "entry": [
                        {"changes": [{"value": {"messages": [{"id": "duplicate-1", "document": {"filename": "dup.pdf", "media_id": "media-z", "mime_type": "application/pdf"}}]}}]}
                    ]
                }
                req1 = urllib.request.Request(
                    f"http://127.0.0.1:{server.server_port}/webhook",
                    data=json.dumps(payload).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                req2 = urllib.request.Request(
                    f"http://127.0.0.1:{server.server_port}/webhook",
                    data=json.dumps(payload).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(req1, timeout=5) as response:
                    first = json.loads(response.read().decode("utf-8"))
                with urllib.request.urlopen(req2, timeout=5) as response:
                    second = json.loads(response.read().decode("utf-8"))
                self.assertEqual(first["processed"], 1)
                self.assertEqual(second["processed"], 1)
                self.assertEqual(len(list((config.archive_root).rglob("*.pdf"))), 1)
            finally:
                server.shutdown()
                server.server_close()

    def test_stale_processing_recovers_on_startup(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            state = ProcessingState(Path(temp_dir) / ".state")
            state = ProcessingState(Path(temp_dir) / ".state")
            with state._connect() as connection:
                connection.execute(
                    "INSERT INTO processing_state (message_id, status, file_path, created_at, updated_at, owner_token, last_error) VALUES (?, 'processing', NULL, ?, ?, 'owner', NULL)",
                    ("stale-1", "2020-01-01T00:00:00+00:00", "2020-01-01T00:00:00+00:00"),
                )
                connection.commit()
            recovered = state.recover_stale_processing(max_age_seconds=1)
            self.assertIn("stale-1", recovered)
            self.assertEqual(state.get_status("stale-1"), "failed")


class ConfigurationTests(unittest.TestCase):
    def test_config_supports_deployment_names(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            original = {
                "ARCHIVE_PATH": str(Path(temp_dir) / "archive"),
                "WHATSAPP_ACCESS_TOKEN": "token-1",
                "WHATSAPP_VERIFY_TOKEN": "verify-1",
                "WEBHOOK_PORT": "9000",
                "WHATSAPP_WEBHOOK_SECRET": "secret-1",
                "LOG_LEVEL": "DEBUG",
            }
            backup = {name: os.environ.get(name) for name in original}
            try:
                for key, value in original.items():
                    os.environ[key] = value
                config = AppConfig.from_env()
                self.assertEqual(str(config.archive_root), original["ARCHIVE_PATH"])
                self.assertEqual(config.access_token, "token-1")
                self.assertEqual(config.webhook_verify_token, "verify-1")
                self.assertEqual(config.listen_port, 9000)
                self.assertEqual(config.webhook_secret, "secret-1")
                self.assertEqual(config.log_level, "DEBUG")
            finally:
                for key, value in backup.items():
                    if value is None:
                        os.environ.pop(key, None)
                    else:
                        os.environ[key] = value


if __name__ == "__main__":
    unittest.main()
