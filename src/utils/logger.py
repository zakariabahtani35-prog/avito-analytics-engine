from __future__ import annotations

import json
import logging
import sys
from typing import Any

from src.config.settings import get_settings
from src.utils.compliance import redact_personal_data


def setup_logging() -> None:
    settings = get_settings()
    root = logging.getLogger()
    if root.handlers:
        return

    root.setLevel(settings.log_level)
    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
    )

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)

    file_handler = logging.FileHandler(
        settings.log_dir / "pipeline.log", encoding="utf-8"
    )
    file_handler.setFormatter(formatter)

    root.addHandler(console_handler)
    root.addHandler(file_handler)


def get_logger(name: str) -> logging.Logger:
    setup_logging()
    return logging.getLogger(name)


def log_event(
    logger: logging.Logger,
    level: int,
    event: str,
    **metadata: Any,
) -> None:
    safe_metadata = {
        key: redact_personal_data(str(value)) if value is not None else None
        for key, value in metadata.items()
    }
    logger.log(level, "%s | %s", event, json.dumps(safe_metadata, ensure_ascii=True))
