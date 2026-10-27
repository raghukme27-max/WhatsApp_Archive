from __future__ import annotations

import logging
import sys

from whatsapp_archive.config import AppConfig
from whatsapp_archive.server import run_server

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


if __name__ == "__main__":
    config = AppConfig.from_env()
    logging.getLogger().setLevel(getattr(logging, config.log_level.upper(), logging.INFO))
    run_server(config)
    sys.exit(0)
