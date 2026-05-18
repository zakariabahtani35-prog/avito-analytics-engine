from __future__ import annotations

import argparse
import json
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
from src.warehouse.reset_data import audit_pipeline_schemas, reset_pipeline_data


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


def _checkpoint_path(batch_id: str) -> Path:
    path = Path("data") / "logs" / f"pipeline_checkpoint_{batch_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def write_checkpoint(batch_id: str, step_name: str, status: str, metadata: dict[str, Any]) -> None:
    checkpoint_file = _checkpoint_path(batch_id)
    if checkpoint_file.exists():
        checkpoint = json.loads(checkpoint_file.read_text(encoding="utf-8"))
    else:
        checkpoint = {"batch_id": batch_id, "steps": []}
    checkpoint["updated_at"] = datetime.now(UTC).isoformat()
    checkpoint["steps"].append(
        {
            "step": step_name,
            "status": status,
            "metadata": _serialize_metadata(metadata),
            "at": datetime.now(UTC).isoformat(),
        }
    )
    checkpoint_file.write_text(json.dumps(checkpoint, indent=2), encoding="utf-8")


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


def collect_pipeline_summary(batch_id: str, quality_report: Path | None = None) -> dict[str, Any]:
    summary: dict[str, Any] = {"batch_id": batch_id}
    with get_connection() as connection:
        with connection.cursor() as cursor:
            for name, query in {
                "total_staged_listings": "SELECT COUNT(*) AS count FROM staging.raw_listings WHERE batch_id = %(batch_id)s;",
                "total_cleaned_listings": "SELECT COUNT(*) AS count FROM clean.clean_listings WHERE batch_id = %(batch_id)s;",
                "total_ml_ready_rows": "SELECT COUNT(*) AS count FROM ml_schema.ml_property_features WHERE batch_id = %(batch_id)s;",
            }.items():
                cursor.execute(query, {"batch_id": batch_id})
                summary[name] = int(cursor.fetchone()["count"])
            cursor.execute(
                """
                SELECT listing_type, COUNT(*) AS count
                FROM clean.clean_listings
                WHERE batch_id = %(batch_id)s
                GROUP BY listing_type
                ORDER BY count DESC;
                """,
                {"batch_id": batch_id},
            )
            summary["sale_vs_rent_distribution"] = list(cursor.fetchall())
            cursor.execute(
                """
                SELECT property_type, COUNT(*) AS count
                FROM clean.clean_listings
                WHERE batch_id = %(batch_id)s
                GROUP BY property_type
                ORDER BY count DESC
                LIMIT 10;
                """,
                {"batch_id": batch_id},
            )
            summary["top_property_types"] = list(cursor.fetchall())
            cursor.execute(
                """
                SELECT city, COUNT(*) AS count
                FROM clean.clean_listings
                WHERE batch_id = %(batch_id)s
                GROUP BY city
                ORDER BY count DESC
                LIMIT 10;
                """,
                {"batch_id": batch_id},
            )
            summary["city_distribution"] = list(cursor.fetchall())
            cursor.execute(
                """
                SELECT
                    ROUND(AVG(CASE WHEN surface_m2 IS NULL THEN 1 ELSE 0 END) * 100, 2) AS surface_m2_missing_pct,
                    ROUND(AVG(CASE WHEN bedrooms IS NULL THEN 1 ELSE 0 END) * 100, 2) AS bedrooms_missing_pct,
                    ROUND(AVG(CASE WHEN bathrooms IS NULL THEN 1 ELSE 0 END) * 100, 2) AS bathrooms_missing_pct,
                    ROUND(AVG(CASE WHEN floor IS NULL THEN 1 ELSE 0 END) * 100, 2) AS floor_missing_pct,
                    ROUND(AVG(CASE WHEN price_per_m2 IS NULL THEN 1 ELSE 0 END) * 100, 2) AS price_per_m2_missing_pct
                FROM ml_schema.ml_property_features
                WHERE batch_id = %(batch_id)s;
                """,
                {"batch_id": batch_id},
            )
            summary["ml_missing_value_statistics"] = cursor.fetchone()
    if quality_report and quality_report.exists():
        report = json.loads(quality_report.read_text(encoding="utf-8"))
        summary["quality_report"] = str(quality_report)
        summary["extraction_success_rate"] = report.get("extraction_success_rate")
        summary["feature_completeness"] = report.get("feature_completeness")
    return summary


def run_pipeline(
    batch_id: str | None = None,
    input_file: Path | None = None,
    reset_data: bool = False,
) -> str:
    logger = get_logger(__name__)
    batch_id = batch_id or new_batch_id()

    log_event(logger, logging.INFO, "pipeline_started", batch_id=batch_id)
    wait_for_database()

    run_with_retry("create_schemas", create_all_schemas)
    audit_result = run_with_retry("audit_pipeline_schemas", audit_pipeline_schemas, retries=0)
    write_checkpoint(batch_id, "audit_pipeline_schemas", "succeeded", _result_metadata(audit_result))
    if reset_data:
        reset_result = run_with_retry("reset_pipeline_data", reset_pipeline_data, retries=0)
        write_checkpoint(batch_id, "reset_pipeline_data", "succeeded", reset_result)

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
        write_checkpoint(batch_id, "scrape_to_raw_csv", "succeeded", _result_metadata(scrape_result))
        raw_file = scrape_result.raw_file

    clean_result = run_with_retry(
        "clean_raw_csv_to_clean_csv",
        lambda: clean_raw_csv_to_clean_csv(raw_file, batch_id),
    )
    write_checkpoint(batch_id, "clean_raw_csv_to_clean_csv", "succeeded", _result_metadata(clean_result))
    staging_rows = run_with_retry(
        "load_raw_csv_to_staging",
        lambda: load_raw_csv_to_staging(raw_file, batch_id),
    )
    write_checkpoint(batch_id, "load_raw_csv_to_staging", "succeeded", {"rows": staging_rows})
    clean_rows = run_with_retry(
        "load_clean_csv_to_clean_table",
        lambda: load_clean_csv_to_clean_table(
            clean_result.clean_file,
            batch_id,
            clean_result.features_file,
        ),
    )
    write_checkpoint(batch_id, "load_clean_csv_to_clean_table", "succeeded", {"rows": clean_rows})
    bi_rows = run_with_retry("load_bi_schema", lambda: load_bi_schema(batch_id))
    write_checkpoint(batch_id, "load_bi_schema", "succeeded", {"rows": bi_rows})
    ml_rows = run_with_retry("load_ml_schema", lambda: load_ml_schema(batch_id))
    write_checkpoint(batch_id, "load_ml_schema", "succeeded", {"rows": ml_rows})

    def checked_quality_results() -> list[Any]:
        results = run_data_quality_checks(
            batch_id=batch_id,
            raw_file=raw_file,
            clean_file=clean_result.clean_file,
            features_file=clean_result.features_file,
        )
        assert_quality_results(results)
        return results

    quality_results = run_with_retry("data_quality_checks", checked_quality_results, retries=0)
    write_checkpoint(batch_id, "data_quality_checks", "succeeded", _result_metadata(quality_results))
    summary = collect_pipeline_summary(batch_id, clean_result.quality_report)
    summary_file = Path("data") / "clean" / f"final_validation_{batch_id}.json"
    summary_file.parent.mkdir(parents=True, exist_ok=True)
    summary_file.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    write_checkpoint(batch_id, "final_validation", "succeeded", {"summary_file": str(summary_file)})

    log_event(
        logger,
        logging.INFO,
        "pipeline_completed",
        batch_id=batch_id,
        raw_file=str(raw_file),
        clean_file=str(clean_result.clean_file),
        features_file=str(clean_result.features_file),
        quality_report=str(clean_result.quality_report),
        final_validation=str(summary_file),
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
    parser.add_argument(
        "--reset-data",
        action="store_true",
        help="Truncate staging, clean, BI, and ML tables before running this batch.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    batch_id = run_pipeline(
        batch_id=args.batch_id,
        input_file=args.input_file,
        reset_data=args.reset_data,
    )
    print(f"Pipeline completed successfully. batch_id={batch_id}")


if __name__ == "__main__":
    main()
