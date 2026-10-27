from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


class ProcessingState:
    def __init__(self, directory: str | os.PathLike[str]):
        self.directory = Path(directory).expanduser()
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / "processed_messages.sqlite3"
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30.0)
        connection.execute("PRAGMA journal_mode=WAL;")
        connection.execute("PRAGMA synchronous=NORMAL;")
        connection.execute("PRAGMA busy_timeout = 30000;")
        connection.execute("PRAGMA foreign_keys = ON;")
        return connection

    def _initialize(self) -> None:
        connection = self._connect()
        try:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS processing_state (
                    message_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL CHECK(status IN ('processing', 'stored', 'duplicate', 'failed')),
                    file_path TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    owner_token TEXT,
                    last_error TEXT
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_processing_state_status ON processing_state(status)"
            )
            connection.commit()
        finally:
            connection.close()

    def _utc_now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def reserve_message(self, message_id: str, owner_token: str | None = None) -> str:
        message_id = str(message_id)
        now = self._utc_now()
        owner_token = owner_token or message_id
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT status, owner_token FROM processing_state WHERE message_id = ?",
                (message_id,),
            ).fetchone()
            if row is None:
                connection.execute(
                    "INSERT INTO processing_state (message_id, status, file_path, created_at, updated_at, owner_token, last_error) VALUES (?, 'processing', NULL, ?, ?, ?, NULL)",
                    (message_id, now, now, owner_token),
                )
                connection.commit()
                return "processing"
            status, current_owner = row
            if status in {"stored", "duplicate"}:
                connection.commit()
                return status
            if status == "processing" and current_owner == owner_token:
                connection.commit()
                return "processing"
            if status == "processing":
                connection.commit()
                return "duplicate"
            connection.execute(
                "UPDATE processing_state SET status = 'processing', updated_at = ?, owner_token = ?, last_error = NULL WHERE message_id = ?",
                (now, owner_token, message_id),
            )
            connection.commit()
            return "processing"
        finally:
            connection.close()

    def is_processed(self, message_id: str) -> bool:
        status = self.get_status(message_id)
        return status in {"stored", "duplicate"}

    def get_status(self, message_id: str) -> str | None:
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT status FROM processing_state WHERE message_id = ?",
                (str(message_id),),
            ).fetchone()
            if row is None:
                return None
            return row[0]
        finally:
            connection.close()

    def mark_processed(self, message_id: str, file_path: str | None = None) -> str:
        now = self._utc_now()
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "INSERT INTO processing_state (message_id, status, file_path, created_at, updated_at, owner_token, last_error) VALUES (?, 'stored', ?, ?, ?, NULL, NULL) ON CONFLICT(message_id) DO UPDATE SET status = 'stored', file_path = excluded.file_path, updated_at = excluded.updated_at, owner_token = NULL, last_error = NULL",
                (str(message_id), file_path, now, now),
            )
            connection.commit()
            return "stored"
        finally:
            connection.close()

    def mark_duplicate(self, message_id: str, file_path: str | None = None) -> str:
        now = self._utc_now()
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "INSERT INTO processing_state (message_id, status, file_path, created_at, updated_at, owner_token, last_error) VALUES (?, 'duplicate', ?, ?, ?, NULL, NULL) ON CONFLICT(message_id) DO UPDATE SET status = 'duplicate', file_path = excluded.file_path, updated_at = excluded.updated_at, owner_token = NULL, last_error = NULL",
                (str(message_id), file_path, now, now),
            )
            connection.commit()
            return "duplicate"
        finally:
            connection.close()

    def mark_failed(self, message_id: str, error: str | None = None) -> str:
        now = self._utc_now()
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "INSERT INTO processing_state (message_id, status, file_path, created_at, updated_at, owner_token, last_error) VALUES (?, 'failed', NULL, ?, ?, NULL, ?) ON CONFLICT(message_id) DO UPDATE SET status = 'failed', updated_at = excluded.updated_at, owner_token = NULL, last_error = excluded.last_error",
                (str(message_id), now, now, error),
            )
            connection.commit()
            return "failed"
        finally:
            connection.close()

    def recover_stale_processing(self, max_age_seconds: int = 3600) -> list[str]:
        cutoff = int(datetime.now(timezone.utc).timestamp() - max_age_seconds)
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute(
                "SELECT message_id FROM processing_state WHERE status = 'processing' AND CAST(strftime('%s', updated_at) AS INTEGER) < ?",
                (cutoff,),
            ).fetchall()
            if not rows:
                connection.commit()
                return []
            ids = [row[0] for row in rows]
            placeholders = ", ".join("?" for _ in ids)
            connection.execute(
                f"UPDATE processing_state SET status = 'failed', updated_at = ?, last_error = 'Recovered stale processing state' WHERE message_id IN ({placeholders})",
                (self._utc_now(), *ids),
            )
            connection.commit()
            return ids
        finally:
            connection.close()

    def clear(self) -> None:
        connection = self._connect()
        try:
            connection.execute("DELETE FROM processing_state")
            connection.commit()
        finally:
            connection.close()
