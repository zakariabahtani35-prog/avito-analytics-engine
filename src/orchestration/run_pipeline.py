from __future__ import annotations

import argparse
import logging
import time
from collections.abc import Callable
from dataclasses import asdict, is_dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypeVar

from src.clean.clean_data import clean_raw_csv_to_clean_csv, load_clean_csv_to_clean_table
from src.extract.scraper import ScrapingStopped, scrape_to_raw_csv
from src.staging.load_staging import load_raw_csv_to_staging
from src.utils.db import get_connection, wait_for_database
from src.utils.logger import get_logger, log_event
from src.validation.data_quality_checks import assert_quality_results, run_data_quality_checks
from src.warehouse.create_schemas import create_all_schemas
from src.warehouse.load_bi_schema import load_bi_schema
from src.warehouse.load_ml_schema import load_ml_schema


T = TypeVar("T")


def new_batch_id() -> str:
    return datetime.now(UTC).strftime("batch_%Y%m%dT%H%M%SZ")


def _serialize_metadata(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {key: _serialize_metadata(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_serialize_metadata(item) for item in value]
    return value


def _result_metadata(result: Any) -> dict[str, Any]:
    if result is None:
        return {}
    if isinstance(result, int):
        return {"rows": result}
    if is_dataclass(result):
        return _serialize_metadata(asdict(result))
    if isinstance(result, list):
        failed = [item for item in result if getattr(item, "passed", True) is False]
        return {"checks": len(result), "failed_checks": len(failed)}
    return {"result": str(result)}


def run_with_retry(
    step_name: str,
    function: Callable[[], T],
    retries: int = 2,
    retry_delay_seconds: float = 3.0,
) -> T:
    logger = get_logger(__name__)
    for attempt in range(1, retries + 2):
        try:
            log_event(logger, logging.INFO, "step_started", step=step_name, attempt=attempt)
            result = function()
            log_event(
                logger,
                logging.INFO,
                "step_succeeded",
                step=step_name,
                **_result_metadata(result),
            )
            return result
        except ScrapingStopped:
            log_event(logger, logging.ERROR, "step_failed", step=step_name, error="ScrapingStopped")
            raise
        except Exception as exc:
            log_event(
                logger,
                logging.ERROR,
                "step_failed",
                step=step_name,
                attempt=attempt,
                error=exc.__class__.__name__,
            )
            if attempt > retries:
                raise
            time.sleep(retry_delay_seconds * attempt)
    raise RuntimeError(f"Unreachable retry state for {step_name}")


def cleanup_staging_batch(batch_id: str) -> None:
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "DELETE FROM staging.raw_listings WHERE batch_id = %(batch_id)s;",
                {"batch_id": batch_id},
            )
        connection.commit()


def run_pipeline(batch_id: str | None = None, input_file: Path | None = None) -> str:
    logger = get_logger(__name__)
    batch_id = batch_id or new_batch_id()

    log_event(logger, logging.INFO, "pipeline_started", batch_id=batch_id)
    wait_for_database()

    run_with_retry("create_schemas", create_all_schemas)

    if input_file:
        raw_file = input_file
        log_event(
            logger,
            logging.INFO,
            "using_existing_raw_csv",
            batch_id=batch_id,
            raw_file=str(raw_file),
        )
    else:
        scrape_result = run_with_retry(
            "scrape_to_raw_csv",
            lambda: scrape_to_raw_csv(batch_id),
            retries=1,
        )
        raw_file = scrape_result.raw_file

    clean_result = run_with_retry(
        "clean_raw_csv_to_clean_csv",
        lambda: clean_raw_csv_to_clean_csv(raw_file, batch_id),
    )
    run_with_retry(
        "load_raw_csv_to_staging",
        lambda: load_raw_csv_to_staging(raw_file, batch_id),
    )
    run_with_retry(
        "load_clean_csv_to_clean_table",
        lambda: load_clean_csv_to_clean_table(
            clean_result.clean_file,
            batch_id,
            clean_result.features_file,
        ),
    )
    run_with_retry("load_bi_schema", lambda: load_bi_schema(batch_id))
    run_with_retry("load_ml_schema", lambda: load_ml_schema(batch_id))

    def checked_quality_results() -> list[Any]:
        results = run_data_quality_checks(
            batch_id=batch_id,
            raw_file=raw_file,
            clean_file=clean_result.clean_file,
            features_file=clean_result.features_file,
        )
        assert_quality_results(results)
        return results

    run_with_retry("data_quality_checks", checked_quality_results, retries=0)

    log_event(
        logger,
        logging.INFO,
        "pipeline_completed",
        batch_id=batch_id,
        raw_file=str(raw_file),
        clean_file=str(clean_result.clean_file),
        features_file=str(clean_result.features_file),
        quality_report=str(clean_result.quality_report),
    )
    return batch_id


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the Avito real estate data pipeline.")
    parser.add_argument("--batch-id", default=None, help="Optional batch id for repeatable runs.")
    parser.add_argument(
        "--input-file",
        type=Path,
        default=None,
        help="Optional sanitized raw CSV file. When provided, scraping is skipped.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    batch_id = run_pipeline(batch_id=args.batch_id, input_file=args.input_file)
    print(f"Pipeline completed successfully. batch_id={batch_id}")


if __name__ == "__main__":
    main()
