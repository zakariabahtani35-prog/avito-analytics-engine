from __future__ import annotations

import csv
import logging
from pathlib import Path
from typing import Any

from src.utils.compliance import (
    RAW_ALLOWED_FIELDS,
    RAW_OUTPUT_CSV_COLUMNS,
    assert_compliant_record,
    sanitize_raw_listing_record,
)
from src.utils.db import get_connection
from src.utils.logger import get_logger, log_event


STAGING_COLUMNS = RAW_OUTPUT_CSV_COLUMNS


def _read_raw_csv(path: Path, batch_id: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8", newline="") as file:
        reader = csv.DictReader(file)
        fieldnames = set(reader.fieldnames or [])
        missing_columns = sorted(set(RAW_OUTPUT_CSV_COLUMNS) - fieldnames)
        if "listing_title_raw" in missing_columns and "listing_title" in fieldnames:
            missing_columns.remove("listing_title_raw")
        if missing_columns:
            raise ValueError(f"Raw CSV missing columns: {missing_columns}")

        for line_number, row in enumerate(reader, start=2):
            raw_record = {column: row.get(column) or None for column in RAW_OUTPUT_CSV_COLUMNS}
            raw_record["listing_title_raw"] = (
                raw_record.get("listing_title_raw") or row.get("listing_title") or None
            )
            raw_record["batch_id"] = batch_id
            raw_record["source"] = raw_record.get("source") or "avito.ma"
            record = sanitize_raw_listing_record(raw_record)
            record["detail_scraped"] = str(record.get("detail_scraped") or "").strip().lower() in {
                "1",
                "true",
                "yes",
                "y",
                "on",
            }
            assert_compliant_record(record, RAW_ALLOWED_FIELDS)
            records.append(record)
            if not record.get("listing_url"):
                log_event(
                    get_logger(__name__),
                    logging.WARNING,
                    "raw_csv_missing_listing_url",
                    file=str(path),
                    line=line_number,
                    batch_id=batch_id,
                )
    return records


def load_raw_csv_to_staging(raw_file: Path, batch_id: str) -> int:
    logger = get_logger(__name__)
    records = _read_raw_csv(raw_file, batch_id)
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "DELETE FROM staging.raw_listings WHERE batch_id = %(batch_id)s;",
                {"batch_id": batch_id},
            )
        connection.commit()

    if not records:
        log_event(logger, logging.WARNING, "staging_no_records", batch_id=batch_id)
        return 0

    placeholders = ", ".join([f"%({column})s" for column in STAGING_COLUMNS])
    columns = ", ".join(STAGING_COLUMNS)
    update_assignments = ", ".join(
        f"{column} = EXCLUDED.{column}"
        for column in STAGING_COLUMNS
        if column != "listing_url"
    )
    query = f"""
        INSERT INTO staging.raw_listings ({columns})
        VALUES ({placeholders})
        ON CONFLICT (listing_url) DO UPDATE
        SET {update_assignments};
    """

    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.executemany(query, records)
        connection.commit()

    log_event(
        logger,
        logging.INFO,
        "raw_csv_loaded_to_staging",
        batch_id=batch_id,
        rows=len(records),
        raw_file=str(raw_file),
    )
    return len(records)


def load_raw_file_to_staging(raw_file: Path, batch_id: str) -> int:
    return load_raw_csv_to_staging(raw_file, batch_id)
