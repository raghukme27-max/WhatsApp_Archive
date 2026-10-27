from __future__ import annotations

import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from whatsapp_archive.models import NormalizedMessage
from whatsapp_archive.state import ProcessingState

_WINDOWS_RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9",
    "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9",
}


class SafeArchiveStorage:
    def __init__(self, archive_root: str | os.PathLike[str], state: ProcessingState):
        self.archive_root = Path(archive_root).expanduser().resolve()
        self.archive_root.mkdir(parents=True, exist_ok=True)
        self.state = state

    @staticmethod
    def sanitize_filename(raw_filename: str) -> str:
        candidate = (raw_filename or "document").strip()
        candidate = candidate.replace("\\", "/")
        candidate = os.path.basename(candidate)
        candidate = candidate.replace("\x00", "")
        candidate = re.sub(r"[<>:\\|\?\*\x00-\x1f]+", "_", candidate)
        candidate = re.sub(r"\s+", "_", candidate)
        candidate = candidate.strip(" .")
        candidate = candidate or "document"
        if candidate in {".", ".."}:
            candidate = "document"

        stem, suffix = os.path.splitext(candidate)
        suffix = (suffix or "").lower()
        if not stem:
            stem = "document"
        if not suffix:
            suffix = ".bin"

        reserved_name = stem.upper()
        if reserved_name in _WINDOWS_RESERVED_NAMES:
            stem = f"_{stem}"

        stem = re.sub(r"[\._]+$", "", stem)
        stem = re.sub(r"\s+", "_", stem)
        stem = re.sub(r"_+", "_", stem).strip("_")
        if not stem:
            stem = "document"
        if len(stem) > 180:
            stem = stem[:180].rstrip("._ ")
        if len(suffix) > 32:
            suffix = suffix[:32]
        return f"{stem}{suffix}"

    def build_destination_path(self, filename: str) -> Path:
        sanitized = self.sanitize_filename(filename)
        timestamp = datetime.now(timezone.utc)
        today_dir = self.archive_root / str(timestamp.year) / f"{timestamp.month:02d}" / f"{timestamp.day:02d}"
        today_dir.mkdir(parents=True, exist_ok=True)

        stem, suffix = os.path.splitext(sanitized)
        candidate = today_dir / sanitized
        counter = 1
        while candidate.exists():
            candidate = today_dir / f"{stem}_{counter}{suffix}"
            counter += 1

        root = self.archive_root.resolve()
        resolved_candidate = candidate.resolve(strict=False)
        if not resolved_candidate.is_relative_to(root):
            raise ValueError(f"Unsafe archive path generated for {filename!r}")

        return candidate

    def write_media(self, message: NormalizedMessage, payload: bytes) -> Path:
        destination = self.build_destination_path(message.filename)
        destination.parent.mkdir(parents=True, exist_ok=True)

        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=str(destination.parent),
            prefix=".upload_",
            suffix=".tmp",
            delete=False,
        ) as temp_file:
            temp_file.write(payload)
            temp_file.flush()
            os.fsync(temp_file.fileno())
            temp_path = Path(temp_file.name)

        try:
            os.replace(temp_path, destination)
        except Exception:
            if temp_path.exists():
                temp_path.unlink(missing_ok=True)
            raise

        if not destination.exists() or destination.stat().st_size != len(payload):
            if destination.exists():
                destination.unlink(missing_ok=True)
            raise OSError(f"Disk write verification failed for {destination}")

        return destination
