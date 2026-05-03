from __future__ import annotations

import logging

from src.config.settings import get_settings
from src.utils.db import execute_sql_files
from src.utils.logger import get_logger, log_event


def create_all_schemas() -> None:
    settings = get_settings()
    sql_files = [
        settings.sql_dir / "01_create_staging.sql",
        settings.sql_dir / "02_create_clean.sql",
        settings.sql_dir / "03_create_bi_schema.sql",
        settings.sql_dir / "04_create_ml_schema.sql",
    ]
    execute_sql_files(sql_files)
    log_event(get_logger(__name__), logging.INFO, "schemas_created")
