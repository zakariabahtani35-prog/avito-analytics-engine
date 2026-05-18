from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[2]
WORKSPACE_ENV_FILE = PROJECT_ROOT.parent / ".env"
PROJECT_ENV_FILE = PROJECT_ROOT / ".env"

_PROCESS_ENV = dict(os.environ)
if WORKSPACE_ENV_FILE.exists():
    load_dotenv(WORKSPACE_ENV_FILE, override=False)
load_dotenv(PROJECT_ENV_FILE, override=True)
for _name, _value in _PROCESS_ENV.items():
    os.environ[_name] = _value


def _get_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _get_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    return int(value)


def _get_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None:
        return default
    return float(value)


def _get_bool_any(names: tuple[str, ...], default: bool) -> bool:
    for name in names:
        value = os.getenv(name)
        if value is not None:
            return value.strip().lower() in {"1", "true", "yes", "y", "on"}
    return default


@dataclass(frozen=True)
class Settings:
    project_root: Path = PROJECT_ROOT
    sql_dir: Path = PROJECT_ROOT / "sql"
    data_dir: Path = PROJECT_ROOT / "data"
    raw_dir: Path = PROJECT_ROOT / "data" / "raw"
    clean_dir: Path = PROJECT_ROOT / "data" / "clean"
    log_dir: Path = PROJECT_ROOT / "data" / "logs"

    db_host: str = os.getenv("DB_HOST", "127.0.0.1")
    db_port: int = _get_int("DB_PORT", 5432)
    db_name: str = os.getenv("DB_NAME", "avito_db")
    db_user: str = os.getenv("DB_USER", "postgres")
    db_password: str = os.getenv("DB_PASSWORD", "")

    avito_search_url: str = os.getenv(
        "AVITO_SEARCH_URL", "https://www.avito.ma/fr/maroc/immobilier"
    )
    scraper_target_listings: int = _get_int("SCRAPER_TARGET_LISTINGS", 10000)
    scraper_max_pages: int = _get_int("SCRAPER_MAX_PAGES", 1000)
    scraper_delay_seconds: float = _get_float("SCRAPER_DELAY_SECONDS", 2.0)
    scraper_timeout_seconds: int = _get_int("SCRAPER_TIMEOUT_SECONDS", 60)
    scraper_max_retries: int = _get_int("SCRAPER_MAX_RETRIES", 3)
    scraper_max_blocked_responses: int = _get_int("SCRAPER_MAX_BLOCKED_RESPONSES", 5)
    scraper_max_empty_pages: int = _get_int("SCRAPER_MAX_EMPTY_PAGES", 3)
    robots_strict: bool = _get_bool_any(("SCRAPER_STRICT_ROBOTS", "ROBOTS_STRICT"), False)
    fetch_detail_pages: bool = _get_bool("FETCH_DETAIL_PAGES", True)
    clean_staging_after_success: bool = _get_bool("CLEAN_STAGING_AFTER_SUCCESS", False)
    log_level: str = os.getenv("LOG_LEVEL", "INFO").upper()

    @property
    def database_url(self) -> str:
        return (
            f"postgresql://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )

    def ensure_directories(self) -> None:
        for directory in (self.raw_dir, self.clean_dir, self.log_dir):
            directory.mkdir(parents=True, exist_ok=True)


def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_directories()
    return settings
