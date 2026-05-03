from __future__ import annotations

import time
import logging
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

try:
    import psycopg
    from psycopg.rows import dict_row
except ImportError as exc:  # pragma: no cover - depends on local Python install
    raise ImportError(
        "PostgreSQL driver unavailable. Install the project dependencies inside "
        "the active virtual environment with: python -m pip install -r requirements.txt. "
        "This project uses psycopg[binary], which bundles the libpq wrapper needed "
        "on Windows and avoids requiring a local PostgreSQL client installation."
    ) from exc

from src.config.settings import get_settings
from src.utils.logger import get_logger, log_event


_DATABASE_CONFIG_LOGGED = False


@contextmanager
def get_connection() -> Iterator[psycopg.Connection[Any]]:
    global _DATABASE_CONFIG_LOGGED
    settings = get_settings()
    if not _DATABASE_CONFIG_LOGGED:
        log_event(
            get_logger(__name__),
            logging.INFO,
            "database_config_loaded",
            DB_HOST=settings.db_host,
            DB_PORT=settings.db_port,
            DB_NAME=settings.db_name,
            DB_USER=settings.db_user,
        )
        _DATABASE_CONFIG_LOGGED = True
    with psycopg.connect(
        settings.database_url,
        row_factory=dict_row,
        connect_timeout=10,
    ) as connection:
        yield connection


def wait_for_database(timeout_seconds: int = 60) -> None:
    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with get_connection() as connection:
                connection.execute("SELECT 1")
                return
        except Exception as exc:  # pragma: no cover - environment dependent
            last_error = exc
            time.sleep(2)
    raise TimeoutError(f"PostgreSQL is not ready after {timeout_seconds}s: {last_error}")


def execute_sql_file(path: Path) -> None:
    sql = path.read_text(encoding="utf-8")
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(sql)
        connection.commit()


def execute_sql_files(paths: Iterable[Path]) -> None:
    for path in paths:
        execute_sql_file(path)


def fetch_scalar(query: str, params: dict[str, Any] | tuple[Any, ...] | None = None) -> Any:
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(query, params)
            row = cursor.fetchone()
            return next(iter(row.values())) if row else None


def fetch_all(
    query: str,
    params: dict[str, Any] | tuple[Any, ...] | None = None,
) -> list[dict[str, Any]]:
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(query, params)
            return list(cursor.fetchall())
