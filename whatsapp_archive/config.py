from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

SUPPORTED_EXTENSIONS = {
    ".pdf",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".ppt",
    ".pptx",
    ".jpg",
    ".jpeg",
    ".png",
}


def _default_archive_root() -> Path:
    if sys.platform.startswith("win"):
        return Path(r"C:\EducationalArchive")
    return Path.home() / "EducationalArchive"


def _getenv(*names: str, default: str = "") -> str:
    for name in names:
        value = os.getenv(name)
        if value is not None:
            return value
    return default


@dataclass(frozen=True)
class AppConfig:
    archive_root: Path
    webhook_verify_token: str = "replace-me"
    webhook_secret: str = ""
    listen_host: str = "127.0.0.1"
    listen_port: int = 8000
    access_token: str = ""
    phone_number_id: str = ""
    api_base_url: str = "https://graph.facebook.com/v18.0"
    api_version: str = "v18.0"
    state_dir: Path | None = None
    max_retries: int = 3
    retry_backoff_seconds: float = 1.0
    max_workers: int = 8
    local_dev_mode: bool = False
    log_level: str = "INFO"

    @classmethod
    def from_env(cls) -> "AppConfig":
        archive_root_value = _getenv("ARCHIVE_PATH", "WA_ARCHIVE_ROOT", default=str(_default_archive_root()))
        archive_root = Path(archive_root_value).expanduser()
        state_dir_value = _getenv("STATE_DB_PATH", "WA_STATE_DIR", default=str(archive_root / ".state"))
        state_dir = Path(state_dir_value).expanduser()
        return cls(
            archive_root=archive_root,
            webhook_verify_token=_getenv("WHATSAPP_VERIFY_TOKEN", "WA_WEBHOOK_VERIFY_TOKEN", default="replace-me"),
            webhook_secret=_getenv("WHATSAPP_WEBHOOK_SECRET", "WA_WEBHOOK_SECRET", default=""),
            listen_host=_getenv("WEBHOOK_HOST", "WA_ARCHIVE_HOST", default="127.0.0.1"),
            listen_port=int(_getenv("WEBHOOK_PORT", "WA_ARCHIVE_PORT", default="8000")),
            access_token=_getenv("WHATSAPP_ACCESS_TOKEN", "WA_ACCESS_TOKEN", default=""),
            phone_number_id=_getenv("WHATSAPP_PHONE_NUMBER_ID", default=""),
            api_base_url=_getenv("WHATSAPP_API_BASE_URL", "WA_API_BASE_URL", default="https://graph.facebook.com/v18.0"),
            api_version=_getenv("WHATSAPP_API_VERSION", default="v18.0"),
            state_dir=state_dir,
            max_retries=int(_getenv("MAX_RETRIES", "WA_MAX_RETRIES", default="3")),
            retry_backoff_seconds=float(_getenv("RETRY_BACKOFF_SECONDS", "WA_RETRY_BACKOFF_SECONDS", default="1.0")),
            max_workers=int(_getenv("MAX_WORKERS", default="8")),
            local_dev_mode=_getenv("LOCAL_DEV_MODE", "WA_ARCHIVE_LOCAL_MODE", default="false").lower() in {"1", "true", "yes", "on"},
            log_level=_getenv("LOG_LEVEL", "WA_LOG_LEVEL", default="INFO").upper(),
        )
