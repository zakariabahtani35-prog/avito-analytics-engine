from __future__ import annotations

import csv
import logging
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from src.clean.clean_data import (
    BATHROOMS_MAX,
    BATHROOMS_MIN,
    BEDROOMS_MAX,
    BEDROOMS_MIN,
    FLOOR_MAX,
    FLOOR_MIN,
    OPTIONAL_FEATURE_COLUMNS,
    PRICE_MAX,
    PRICE_MIN,
    PRICE_PER_M2_MAX,
    PRICE_PER_M2_MIN,
    REQUIRED_CLEAN_COLUMNS,
    SURFACE_MAX,
    SURFACE_MIN,
)
from src.config.settings import get_settings
from src.utils.compliance import (
    CLEAN_CORE_CSV_COLUMNS,
    CLEAN_FEATURE_CSV_COLUMNS,
    RAW_CSV_COLUMNS,
    RAW_OUTPUT_CSV_COLUMNS,
    contains_personal_data,
)
from src.utils.db import get_connection
from src.utils.logger import get_logger, log_event


EMAIL_SQL_RE = r"[^@[:space:]]+@[^@[:space:]]+\.[^@[:space:]]+"
PHONE_SQL_RE = r"(\+?212|0)[[:space:].-]?[567][[:space:].-]?[0-9][0-9[:space:].-]{6,}"
NON_PRIVACY_TEXT_COLUMNS = {
    "listing_url",
    "scraped_at",
    "batch_id",
    "price",
    "price_raw",
    "description_raw",
    "description_clean",
    "surface_m2",
    "surface_raw",
    "bedrooms",
    "bedrooms_raw",
    "bathrooms",
    "bathrooms_raw",
    "floor",
    "floor_raw",
    "construction_year",
    "construction_year_raw",
    "price_per_m2",
    "property_age",
    "property_type",
    "property_type_raw",
    "listing_type",
    "listing_type_raw",
    "latitude",
    "longitude",
    "latitude_raw",
    "longitude_raw",
    "attributes_raw",
    "rooms_total",
    "price_per_room",
    "room_density",
    "luxury_flag",
    "coastal_city",
    "surface_x_rooms",
    "bathrooms_per_bedroom",
    "extraction_score",
    "feature_completeness_score",
    "detail_scraped",
}


@dataclass(frozen=True)
class QualityResult:
    check_name: str
    passed: bool
    bad_rows: int
    details: str


def _batch_filter(alias: str = "") -> str:
    prefix = f"{alias}." if alias else ""
    return f" AND {prefix}batch_id = %(batch_id)s"


def _default_raw_file(batch_id: str | None) -> Path | None:
    if not batch_id:
        return None
    return get_settings().raw_dir / f"avito_raw_{batch_id}.csv"


def _default_clean_file(batch_id: str | None) -> Path | None:
    if not batch_id:
        return None
    return get_settings().clean_dir / f"avito_clean_core_{batch_id}.csv"


def _default_features_file(batch_id: str | None) -> Path | None:
    if not batch_id:
        return None
    return get_settings().clean_dir / f"avito_clean_features_{batch_id}.csv"


def _read_csv_rows(
    path: Path,
    required_columns: list[str],
    *,
    allowed_columns: list[str] | None = None,
) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8", newline="") as file:
        reader = csv.DictReader(file)
        fieldnames = reader.fieldnames or []
        missing_columns = sorted(set(required_columns) - set(fieldnames))
        if missing_columns:
            raise ValueError(f"{path} missing columns: {missing_columns}")
        if allowed_columns is not None:
            unexpected_columns = sorted(set(fieldnames) - set(allowed_columns))
            if unexpected_columns:
                raise ValueError(f"{path} has unsupported columns: {unexpected_columns}")
        return [{column: row.get(column) or None for column in fieldnames} for row in reader]


def _read_raw_csv_rows(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8", newline="") as file:
        reader = csv.DictReader(file)
        fieldnames = reader.fieldnames or []
        required_columns = set(RAW_OUTPUT_CSV_COLUMNS)
        if "listing_title_raw" not in fieldnames and "listing_title" in fieldnames:
            required_columns.remove("listing_title_raw")
        missing_columns = sorted(required_columns - set(fieldnames))
        if missing_columns:
            raise ValueError(f"{path} missing columns: {missing_columns}")
        unexpected_columns = sorted(set(fieldnames) - set(RAW_CSV_COLUMNS))
        if unexpected_columns:
            raise ValueError(f"{path} has unsupported columns: {unexpected_columns}")
        return [{column: row.get(column) or None for column in fieldnames} for row in reader]


def _to_decimal(value: Any) -> Decimal | None:
    if value in {None, ""}:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _to_int(value: Any) -> int | None:
    number = _to_decimal(value)
    if number is None:
        return None
    return int(number)


def _csv_personal_pattern_check(rows: list[dict[str, Any]]) -> QualityResult:
    bad_rows = 0
    for row in rows:
        if any(
            contains_personal_data(str(value))
            for column, value in row.items()
            if value and column not in NON_PRIVACY_TEXT_COLUMNS
        ):
            bad_rows += 1
    return QualityResult(
        "csv_no_personal_data_patterns",
        bad_rows == 0,
        bad_rows,
        "Email or Moroccan phone patterns in raw/clean CSV files",
    )


def _optional_completeness_results(
    feature_rows: list[dict[str, Any]],
    core_row_count: int,
) -> list[QualityResult]:
    results: list[QualityResult] = []
    for column in OPTIONAL_FEATURE_COLUMNS:
        present_count = sum(1 for row in feature_rows if row.get(column) not in {None, ""})
        missing_count = max(core_row_count - present_count, 0)
        completeness = 0.0 if core_row_count == 0 else present_count / core_row_count
        results.append(
            QualityResult(
                f"warning_optional_{column}_completeness",
                True,
                missing_count,
                f"completeness_rate={completeness:.2%}",
            )
        )
    return results


def _clean_csv_checks(clean_rows: list[dict[str, Any]]) -> list[QualityResult]:
    checks: list[QualityResult] = []

    urls = [row.get("listing_url") for row in clean_rows if row.get("listing_url")]
    duplicate_count = len(urls) - len(set(urls))
    checks.append(
        QualityResult(
            "clean_csv_no_duplicate_listing_url",
            duplicate_count == 0,
            duplicate_count,
            "Duplicate listing_url in clean CSV",
        )
    )

    required_null_rows = sum(
        1
        for row in clean_rows
        if any(row.get(column) in {None, ""} for column in REQUIRED_CLEAN_COLUMNS)
    )
    checks.append(
        QualityResult(
            "clean_csv_required_columns_not_null",
            required_null_rows == 0,
            required_null_rows,
            f"Required columns: {', '.join(REQUIRED_CLEAN_COLUMNS)}",
        )
    )

    bad_price_count = sum(
        1
        for row in clean_rows
        if (price := _to_decimal(row.get("price"))) is None
        or price < PRICE_MIN
        or price > PRICE_MAX
    )
    checks.append(
        QualityResult(
            "warning_clean_csv_realistic_price",
            True,
            bad_price_count,
            f"price must be between {PRICE_MIN} and {PRICE_MAX}",
        )
    )

    short_title_count = sum(
        1 for row in clean_rows if len(str(row.get("listing_title_clean") or "")) < 15
    )
    checks.append(
        QualityResult(
            "warning_clean_csv_title_length",
            True,
            short_title_count,
            "listing_title_clean length must be >= 15",
        )
    )

    return checks


def _features_csv_checks(
    core_rows: list[dict[str, Any]],
    feature_rows: list[dict[str, Any]],
) -> list[QualityResult]:
    checks: list[QualityResult] = []
    core_by_url = {
        row["listing_url"]: row
        for row in core_rows
        if row.get("listing_url")
    }

    urls = [row.get("listing_url") for row in feature_rows if row.get("listing_url")]
    duplicate_count = len(urls) - len(set(urls))
    checks.append(
        QualityResult(
            "features_csv_no_duplicate_listing_url",
            duplicate_count == 0,
            duplicate_count,
            "Duplicate listing_url in features CSV",
        )
    )

    missing_core_count = sum(1 for url in urls if url not in core_by_url)
    checks.append(
        QualityResult(
            "features_csv_join_key_matches_core",
            missing_core_count == 0,
            missing_core_count,
            "Every features listing_url must exist in the core CSV",
        )
    )

    optional_invalid_count = 0
    for row in feature_rows:
        surface = _to_decimal(row.get("surface_m2"))
        bedrooms = _to_int(row.get("bedrooms"))
        bathrooms = _to_int(row.get("bathrooms"))
        floor = _to_int(row.get("floor"))
        price_per_m2 = _to_decimal(row.get("price_per_m2"))
        if surface is not None and (surface < SURFACE_MIN or surface > SURFACE_MAX):
            optional_invalid_count += 1
        if bedrooms is not None and (bedrooms < BEDROOMS_MIN or bedrooms > BEDROOMS_MAX):
            optional_invalid_count += 1
        if bathrooms is not None and (bathrooms < BATHROOMS_MIN or bathrooms > BATHROOMS_MAX):
            optional_invalid_count += 1
        if floor is not None and (floor < FLOOR_MIN or floor > FLOOR_MAX):
            optional_invalid_count += 1
        if price_per_m2 is not None and (
            price_per_m2 < PRICE_PER_M2_MIN or price_per_m2 > PRICE_PER_M2_MAX
        ):
            optional_invalid_count += 1
    checks.append(
        QualityResult(
            "warning_features_csv_optional_values_out_of_range",
            True,
            optional_invalid_count,
            "Optional feature values should be within expected ranges",
        )
    )

    bad_ppm_count = 0
    for row in feature_rows:
        price_per_m2 = _to_decimal(row.get("price_per_m2"))
        if price_per_m2 is None:
            continue
        core_row = core_by_url.get(row.get("listing_url"))
        price = _to_decimal(core_row.get("price")) if core_row else None
        surface = _to_decimal(row.get("surface_m2"))
        if price is None or surface is None or surface <= 0:
            bad_ppm_count += 1
            continue
        if abs(price_per_m2 - (price / surface).quantize(Decimal("0.01"))) > Decimal("0.01"):
            bad_ppm_count += 1
    checks.append(
        QualityResult(
            "warning_features_csv_price_per_m2_quality",
            True,
            bad_ppm_count,
            "price_per_m2 must be present only when price and surface_m2 are valid",
        )
    )

    checks.extend(_optional_completeness_results(feature_rows, len(core_rows)))
    return checks


def _file_quality_checks(
    batch_id: str | None,
    raw_file: Path | None,
    clean_file: Path | None,
    features_file: Path | None,
) -> tuple[list[QualityResult], list[dict[str, Any]], list[dict[str, Any]]]:
    raw_path = raw_file or _default_raw_file(batch_id)
    clean_path = clean_file or _default_clean_file(batch_id)
    features_path = features_file or _default_features_file(batch_id)
    checks: list[QualityResult] = []
    all_csv_rows: list[dict[str, Any]] = []
    clean_rows: list[dict[str, Any]] = []
    feature_rows: list[dict[str, Any]] = []

    raw_exists = bool(raw_path and raw_path.exists())
    checks.append(
        QualityResult(
            "raw_csv_exists",
            raw_exists,
            0 if raw_exists else 1,
            str(raw_path) if raw_path else "batch_id not provided",
        )
    )
    if raw_exists and raw_path:
        raw_rows = _read_raw_csv_rows(raw_path)
        all_csv_rows.extend(raw_rows)

    clean_exists = bool(clean_path and clean_path.exists())
    checks.append(
        QualityResult(
            "clean_csv_exists",
            clean_exists,
            0 if clean_exists else 1,
            str(clean_path) if clean_path else "batch_id not provided",
        )
    )
    if clean_exists and clean_path:
        clean_rows = _read_csv_rows(
            clean_path,
            REQUIRED_CLEAN_COLUMNS,
            allowed_columns=CLEAN_CORE_CSV_COLUMNS,
        )
        all_csv_rows.extend(clean_rows)
        checks.extend(_clean_csv_checks(clean_rows))

    features_exists = bool(features_path and features_path.exists())
    checks.append(
        QualityResult(
            "features_csv_exists",
            features_exists,
            0 if features_exists else 1,
            str(features_path) if features_path else "batch_id not provided",
        )
    )
    if features_exists and features_path:
        feature_rows = _read_csv_rows(
            features_path,
            ["listing_url", *OPTIONAL_FEATURE_COLUMNS],
            allowed_columns=CLEAN_FEATURE_CSV_COLUMNS,
        )
        all_csv_rows.extend(feature_rows)
        checks.extend(_features_csv_checks(clean_rows, feature_rows))

    if all_csv_rows:
        checks.append(_csv_personal_pattern_check(all_csv_rows))
    return checks, clean_rows, feature_rows


def _db_table_exists(cursor: Any, schema: str, table: str) -> bool:
    cursor.execute(
        """
        SELECT EXISTS (
            SELECT 1
            FROM information_schema.tables
            WHERE table_schema = %(schema)s
              AND table_name = %(table)s
        ) AS exists;
        """,
        {"schema": schema, "table": table},
    )
    return bool(cursor.fetchone()["exists"])


def _db_available_columns(
    cursor: Any,
    schema: str,
    table: str,
    columns: list[str],
) -> set[str]:
    cursor.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = %(schema)s
          AND table_name = %(table)s
          AND column_name = ANY(%(columns)s);
        """,
        {"schema": schema, "table": table, "columns": columns},
    )
    return {row["column_name"] for row in cursor.fetchall()}


def run_data_quality_checks(
    batch_id: str | None = None,
    raw_file: Path | None = None,
    clean_file: Path | None = None,
    features_file: Path | None = None,
) -> list[QualityResult]:
    logger = get_logger(__name__)
    params = {"batch_id": batch_id}
    batch_clause = _batch_filter() if batch_id else ""
    cl_batch_clause = _batch_filter("cl") if batch_id else ""
    fl_batch_clause = _batch_filter("fl") if batch_id else ""

    checks, clean_csv_rows, _feature_csv_rows = _file_quality_checks(
        batch_id,
        raw_file,
        clean_file,
        features_file,
    )

    with get_connection() as connection:
        with connection.cursor() as cursor:
            features_table_exists = _db_table_exists(cursor, "clean", "clean_listing_features")
            available_feature_columns = (
                _db_available_columns(
                    cursor,
                    "clean",
                    "clean_listing_features",
                    OPTIONAL_FEATURE_COLUMNS,
                )
                if features_table_exists
                else set()
            )
            cursor.execute(
                f"""
                SELECT COUNT(*) AS bad_rows
                FROM clean.clean_listings
                WHERE (
                    (
                        COALESCE(listing_title_clean, '') || ' ' ||
                        COALESCE(description_clean, '') || ' ' ||
                        COALESCE(city, '') || ' ' ||
                        COALESCE(district, '') || ' ' ||
                        COALESCE(property_type, '') || ' ' ||
                        COALESCE(listing_type, '')
                    ) ~* %(email_re)s
                    OR (
                        COALESCE(listing_title_clean, '') || ' ' ||
                        COALESCE(description_clean, '') || ' ' ||
                        COALESCE(city, '') || ' ' ||
                        COALESCE(district, '') || ' ' ||
                        COALESCE(property_type, '') || ' ' ||
                        COALESCE(listing_type, '')
                    ) ~* %(phone_re)s
                )
                {batch_clause};
                """,
                {**params, "email_re": EMAIL_SQL_RE, "phone_re": PHONE_SQL_RE},
            )
            bad_rows = cursor.fetchone()["bad_rows"]
            checks.append(
                QualityResult(
                    "db_no_personal_data_patterns",
                    bad_rows == 0,
                    int(bad_rows),
                    "Email or Moroccan phone patterns in clean table text fields",
                )
            )

            cursor.execute(
                f"""
                SELECT COUNT(*) AS bad_rows
                FROM (
                    SELECT listing_url
                    FROM clean.clean_listings
                    WHERE listing_url IS NOT NULL {batch_clause}
                    GROUP BY listing_url
                    HAVING COUNT(*) > 1
                ) duplicates;
                """,
                params,
            )
            bad_rows = cursor.fetchone()["bad_rows"]
            checks.append(
                QualityResult(
                    "db_no_duplicate_listing_url",
                    bad_rows == 0,
                    int(bad_rows),
                    "Duplicate listing_url in clean table",
                )
            )

            cursor.execute(
                f"""
                SELECT COUNT(*) AS bad_rows
                FROM clean.clean_listings
                WHERE (
                    listing_title_clean IS NULL
                    OR price IS NULL
                    OR city IS NULL
                    OR district IS NULL
                    OR property_type IS NULL
                    OR listing_type IS NULL
                    OR listing_type NOT IN ('sale', 'rent')
                    OR listing_url IS NULL
                    OR scraped_at IS NULL
                    OR batch_id IS NULL
                )
                {batch_clause};
                """,
                params,
            )
            bad_rows = cursor.fetchone()["bad_rows"]
            checks.append(
                QualityResult(
                    "db_required_columns_not_null",
                    bad_rows == 0,
                    int(bad_rows),
                    "Required clean columns must not be NULL",
                )
            )

            cursor.execute(
                f"""
                SELECT COUNT(*) AS bad_rows
                FROM clean.clean_listings
                WHERE (
                    LENGTH(listing_title_clean) < 15
                    OR price < {PRICE_MIN}
                    OR price > {PRICE_MAX}
                )
                {batch_clause};
                """,
                params,
            )
            bad_rows = cursor.fetchone()["bad_rows"]
            checks.append(
                QualityResult(
                    "warning_db_required_value_quality",
                    True,
                    int(bad_rows),
                    "Required values are present but should still look realistic",
                )
            )

            optional_conditions = []
            if "surface_m2" in available_feature_columns:
                optional_conditions.append(
                    f"(feat.surface_m2 IS NOT NULL AND (feat.surface_m2 < {SURFACE_MIN} OR feat.surface_m2 > {SURFACE_MAX}))"
                )
            if "bedrooms" in available_feature_columns:
                optional_conditions.append(
                    f"(feat.bedrooms IS NOT NULL AND (feat.bedrooms < {BEDROOMS_MIN} OR feat.bedrooms > {BEDROOMS_MAX}))"
                )
            if "bathrooms" in available_feature_columns:
                optional_conditions.append(
                    f"(feat.bathrooms IS NOT NULL AND (feat.bathrooms < {BATHROOMS_MIN} OR feat.bathrooms > {BATHROOMS_MAX}))"
                )
            if "floor" in available_feature_columns:
                optional_conditions.append(
                    f"(feat.floor IS NOT NULL AND (feat.floor < {FLOOR_MIN} OR feat.floor > {FLOOR_MAX}))"
                )
            if "price_per_m2" in available_feature_columns:
                optional_conditions.append(
                    f"(feat.price_per_m2 IS NOT NULL AND (feat.price_per_m2 < {PRICE_PER_M2_MIN} OR feat.price_per_m2 > {PRICE_PER_M2_MAX}))"
                )
            if features_table_exists and optional_conditions:
                cursor.execute(
                    f"""
                    SELECT COUNT(*) AS bad_rows
                    FROM clean.clean_listing_features feat
                    JOIN clean.clean_listings cl ON cl.listing_url = feat.listing_url
                    WHERE ({' OR '.join(optional_conditions)})
                    {cl_batch_clause};
                    """,
                    params,
                )
                bad_rows = cursor.fetchone()["bad_rows"]
            else:
                bad_rows = 0
            checks.append(
                QualityResult(
                    "warning_db_optional_values_out_of_range",
                    True,
                    int(bad_rows),
                    "Optional values outside expected ranges should be reviewed",
                )
            )

            if {"surface_m2", "price_per_m2"}.issubset(available_feature_columns):
                cursor.execute(
                    f"""
                    SELECT COUNT(*) AS bad_rows
                    FROM clean.clean_listing_features feat
                    JOIN clean.clean_listings cl ON cl.listing_url = feat.listing_url
                    WHERE feat.price_per_m2 IS NOT NULL
                      AND (
                          cl.price IS NULL
                          OR feat.surface_m2 IS NULL
                          OR feat.surface_m2 <= 0
                          OR ABS(feat.price_per_m2 - ROUND(cl.price / feat.surface_m2, 2)) > 0.01
                      )
                      {cl_batch_clause};
                    """,
                    params,
                )
                bad_rows = cursor.fetchone()["bad_rows"]
            else:
                bad_rows = 0
            checks.append(
                QualityResult(
                    "db_price_per_m2_coherence",
                    bad_rows == 0,
                    int(bad_rows),
                    "price_per_m2 must equal price / surface_m2",
                )
            )

            cursor.execute(
                f"SELECT COUNT(*) AS count FROM clean.clean_listings WHERE TRUE {batch_clause};",
                params,
            )
            clean_count = int(cursor.fetchone()["count"])

            if clean_csv_rows:
                checks.append(
                    QualityResult(
                        "clean_table_count_equals_clean_csv",
                        clean_count == len(clean_csv_rows),
                        abs(clean_count - len(clean_csv_rows)),
                        f"clean_table={clean_count}, clean_csv={len(clean_csv_rows)}",
                    )
                )

            cursor.execute(
                f"SELECT COUNT(*) AS count FROM bi_schema.fact_listing WHERE TRUE {batch_clause};",
                params,
            )
            fact_count = int(cursor.fetchone()["count"])
            checks.append(
                QualityResult(
                    "bi_fact_count_equals_clean_count",
                    fact_count == clean_count,
                    abs(fact_count - clean_count),
                    f"fact={fact_count}, clean={clean_count}",
                )
            )

            cursor.execute(
                f"SELECT COUNT(*) AS count FROM ml_schema.ml_property_features WHERE TRUE {batch_clause};",
                params,
            )
            ml_count = int(cursor.fetchone()["count"])
            cursor.execute(
                f"""
                SELECT COUNT(*) AS count
                FROM clean.clean_listings
                WHERE listing_type = 'sale' {batch_clause};
                """,
                params,
            )
            sale_clean_count = int(cursor.fetchone()["count"])
            checks.append(
                QualityResult(
                    "ml_count_not_greater_than_sale_clean_count",
                    ml_count <= sale_clean_count,
                    max(ml_count - sale_clean_count, 0),
                    f"ml={ml_count}, sale_clean={sale_clean_count}, clean={clean_count}",
                )
            )

            cursor.execute(
                f"""
                SELECT COUNT(*) AS bad_rows
                FROM ml_schema.ml_property_features
                WHERE listing_type <> 'sale' OR listing_type IS NULL
                {batch_clause};
                """,
                params,
            )
            bad_rows = cursor.fetchone()["bad_rows"]
            checks.append(
                QualityResult(
                    "ml_no_rental_contamination",
                    bad_rows == 0,
                    int(bad_rows),
                    "ML OBT must contain only sale listings",
                )
            )

            cursor.execute(
                f"""
                SELECT COUNT(*) AS bad_rows
                FROM bi_schema.fact_listing fl
                LEFT JOIN bi_schema.dim_time dt ON dt.time_id = fl.time_id
                LEFT JOIN bi_schema.dim_location dl ON dl.location_id = fl.location_id
                LEFT JOIN clean.clean_listings cl ON cl.listing_url = fl.listing_url
                WHERE (dt.time_id IS NULL OR dl.location_id IS NULL
                       OR cl.listing_url IS NULL)
                  {fl_batch_clause};
                """,
                params,
            )
            bad_rows = cursor.fetchone()["bad_rows"]
            checks.append(
                QualityResult(
                    "foreign_keys_integrity",
                    bad_rows == 0,
                    int(bad_rows),
                    "Fact rows must link to all dimensions and clean rows",
                )
            )

    for check in checks:
        level = logging.INFO if check.passed else logging.ERROR
        if check.passed and check.bad_rows and check.check_name.startswith("warning_"):
            level = logging.WARNING
        log_event(
            logger,
            level,
            "quality_check",
            check=check.check_name,
            passed=check.passed,
            bad_rows=check.bad_rows,
            details=check.details,
        )
    return checks


def assert_quality_results(results: list[QualityResult]) -> None:
    failures = [result for result in results if not result.passed]
    if failures:
        summary = ", ".join(f"{failure.check_name}={failure.bad_rows}" for failure in failures)
        raise AssertionError(f"Data quality failed: {summary}")
