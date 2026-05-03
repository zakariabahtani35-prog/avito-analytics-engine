from __future__ import annotations

import logging
from typing import Any

from src.utils.db import get_connection
from src.utils.logger import get_logger, log_event


OPTIONAL_FEATURE_COLUMNS = [
    "surface_m2",
    "bedrooms",
    "bathrooms",
    "floor",
    "price_per_m2",
]
OPTIONAL_SQL_TYPES = {
    "surface_m2": "NUMERIC",
    "bedrooms": "INTEGER",
    "bathrooms": "INTEGER",
    "floor": "INTEGER",
    "price_per_m2": "NUMERIC",
}


def _table_exists(cursor: Any, schema: str, table: str) -> bool:
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


def _available_table_columns(
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


def _feature_column_expr(column: str, available_columns: set[str]) -> str:
    if column in available_columns:
        return f"feat.{column}"
    return f"NULL::{OPTIONAL_SQL_TYPES[column]}"


def load_ml_schema(batch_id: str) -> int:
    logger = get_logger(__name__)
    with get_connection() as connection:
        with connection.cursor() as cursor:
            features_table_exists = _table_exists(cursor, "clean", "clean_listing_features")
            available_feature_columns = (
                _available_table_columns(
                    cursor,
                    "clean",
                    "clean_listing_features",
                    OPTIONAL_FEATURE_COLUMNS,
                )
                if features_table_exists
                else set()
            )
            optional_select_sql = ",\n                        ".join(
                f"{_feature_column_expr(column, available_feature_columns)} AS {column}"
                for column in OPTIONAL_FEATURE_COLUMNS
            )
            feature_join_sql = (
                "LEFT JOIN clean.clean_listing_features feat ON feat.listing_url = src.listing_url"
                if features_table_exists
                else ""
            )

            cursor.execute(
                "DELETE FROM ml_schema.ml_property_features WHERE batch_id = %(batch_id)s;",
                {"batch_id": batch_id},
            )
            cursor.execute(
                f"""
                INSERT INTO ml_schema.ml_property_features (
                    listing_url, price, city, district, surface_m2, bedrooms, bathrooms,
                    floor, price_per_m2, scraped_year, scraped_month, batch_id
                )
                SELECT
                    src.listing_url,
                    src.price,
                    src.city,
                    src.district,
                    {optional_select_sql},
                    EXTRACT(YEAR FROM src.scraped_at)::int AS scraped_year,
                    EXTRACT(MONTH FROM src.scraped_at)::int AS scraped_month,
                    src.batch_id
                FROM clean.clean_listings src
                {feature_join_sql}
                WHERE src.batch_id = %(batch_id)s
                ON CONFLICT (listing_url) DO UPDATE SET
                    price = EXCLUDED.price,
                    city = EXCLUDED.city,
                    district = EXCLUDED.district,
                    surface_m2 = EXCLUDED.surface_m2,
                    bedrooms = EXCLUDED.bedrooms,
                    bathrooms = EXCLUDED.bathrooms,
                    floor = EXCLUDED.floor,
                    price_per_m2 = EXCLUDED.price_per_m2,
                    scraped_year = EXCLUDED.scraped_year,
                    scraped_month = EXCLUDED.scraped_month,
                    batch_id = EXCLUDED.batch_id;
                """,
                {"batch_id": batch_id},
            )
            cursor.execute(
                "SELECT COUNT(*) AS count FROM ml_schema.ml_property_features WHERE batch_id = %(batch_id)s;",
                {"batch_id": batch_id},
            )
            loaded_count = cursor.fetchone()["count"]
        connection.commit()

    log_event(
        logger,
        logging.INFO,
        "ml_schema_loaded",
        batch_id=batch_id,
        rows=loaded_count,
        feature_table_available=features_table_exists,
    )
    return int(loaded_count)
