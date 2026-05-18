from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from src.utils.db import get_connection
from src.utils.logger import get_logger, log_event


SCHEMA_TABLES = {
    "staging": ["raw_listings"],
    "clean": ["clean_listing_features", "clean_listings"],
    "bi_schema": ["fact_listing", "dim_location", "dim_time"],
    "ml_schema": ["ml_property_features"],
}

EXPECTED_COLUMNS = {
    ("staging", "raw_listings"): {
        "listing_title_raw",
        "description_raw",
        "price_raw",
        "city_raw",
        "district_raw",
        "property_type_raw",
        "listing_type_raw",
        "surface_raw",
        "bedrooms_raw",
        "bathrooms_raw",
        "floor_raw",
        "latitude_raw",
        "longitude_raw",
        "construction_year_raw",
        "attributes_raw",
        "listing_url",
        "scraped_at",
        "batch_id",
        "source",
        "detail_scraped",
    },
    ("clean", "clean_listings"): {
        "listing_title_clean",
        "description_clean",
        "price",
        "city",
        "district",
        "property_type",
        "listing_type",
        "latitude",
        "longitude",
        "listing_url",
        "scraped_at",
        "batch_id",
    },
    ("clean", "clean_listing_features"): {
        "listing_url",
        "surface_m2",
        "bedrooms",
        "bathrooms",
        "floor",
        "construction_year",
        "property_age",
        "price_per_m2",
        "rooms_total",
        "price_per_room",
        "room_density",
        "luxury_flag",
        "coastal_city",
        "property_age_bucket",
        "surface_x_rooms",
        "bathrooms_per_bedroom",
        "extraction_score",
        "feature_completeness_score",
        "batch_id",
    },
    ("ml_schema", "ml_property_features"): {
        "listing_url",
        "price",
        "log_price",
        "city",
        "district",
        "property_type",
        "listing_type",
        "surface_m2",
        "bedrooms",
        "bathrooms",
        "floor",
        "construction_year",
        "property_age",
        "price_per_m2",
        "rooms_total",
        "price_per_room",
        "room_density",
        "luxury_flag",
        "coastal_city",
        "district_market_index",
        "city_market_index",
        "property_age_bucket",
        "surface_x_rooms",
        "bathrooms_per_bedroom",
        "latitude",
        "longitude",
        "feature_completeness_score",
        "scraped_year",
        "scraped_month",
        "batch_id",
    },
}


@dataclass(frozen=True)
class SchemaAuditResult:
    missing_tables: list[str]
    missing_columns: dict[str, list[str]]
    row_counts: dict[str, int]


def audit_pipeline_schemas() -> SchemaAuditResult:
    missing_tables: list[str] = []
    missing_columns: dict[str, list[str]] = {}
    row_counts: dict[str, int] = {}
    with get_connection() as connection:
        with connection.cursor() as cursor:
            for schema, tables in SCHEMA_TABLES.items():
                for table in tables:
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
                    table_key = f"{schema}.{table}"
                    if not cursor.fetchone()["exists"]:
                        missing_tables.append(table_key)
                        continue

                    cursor.execute(
                        """
                        SELECT column_name
                        FROM information_schema.columns
                        WHERE table_schema = %(schema)s
                          AND table_name = %(table)s;
                        """,
                        {"schema": schema, "table": table},
                    )
                    available = {row["column_name"] for row in cursor.fetchall()}
                    expected = EXPECTED_COLUMNS.get((schema, table), set())
                    missing = sorted(expected - available)
                    if missing:
                        missing_columns[table_key] = missing

                    cursor.execute(f"SELECT COUNT(*) AS count FROM {schema}.{table};")
                    row_counts[table_key] = int(cursor.fetchone()["count"])

    log_event(
        get_logger(__name__),
        logging.INFO,
        "schema_audit_completed",
        missing_tables=missing_tables,
        missing_columns=missing_columns,
        row_counts=row_counts,
    )
    return SchemaAuditResult(missing_tables, missing_columns, row_counts)


def reset_pipeline_data() -> dict[str, int]:
    """Remove pipeline data while keeping schemas, tables, constraints, and indexes."""

    before_counts: dict[str, int] = {}
    table_refs = [
        "ml_schema.ml_property_features",
        "bi_schema.fact_listing",
        "bi_schema.dim_location",
        "bi_schema.dim_time",
        "clean.clean_listing_features",
        "clean.clean_listings",
        "staging.raw_listings",
    ]
    with get_connection() as connection:
        with connection.cursor() as cursor:
            for table_ref in table_refs:
                cursor.execute(f"SELECT COUNT(*) AS count FROM {table_ref};")
                before_counts[table_ref] = int(cursor.fetchone()["count"])
            cursor.execute(
                """
                TRUNCATE TABLE
                    ml_schema.ml_property_features,
                    bi_schema.fact_listing,
                    bi_schema.dim_location,
                    bi_schema.dim_time,
                    clean.clean_listing_features,
                    clean.clean_listings,
                    staging.raw_listings
                RESTART IDENTITY CASCADE;
                """
            )
        connection.commit()

    log_event(
        get_logger(__name__),
        logging.WARNING,
        "pipeline_data_reset_completed",
        rows_removed=before_counts,
    )
    return before_counts
