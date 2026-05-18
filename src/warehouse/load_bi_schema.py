from __future__ import annotations

import logging

from src.utils.db import get_connection
from src.utils.logger import get_logger, log_event


def load_bi_schema(batch_id: str) -> int:
    logger = get_logger(__name__)
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO bi_schema.dim_time (date, year, month, month_name, quarter)
                SELECT DISTINCT
                    scraped_at::date AS date,
                    EXTRACT(YEAR FROM scraped_at)::int AS year,
                    EXTRACT(MONTH FROM scraped_at)::int AS month,
                    TO_CHAR(scraped_at, 'FMMonth') AS month_name,
                    EXTRACT(QUARTER FROM scraped_at)::int AS quarter
                FROM clean.clean_listings
                WHERE batch_id = %(batch_id)s
                  AND scraped_at IS NOT NULL
                ON CONFLICT (date) DO NOTHING;
                """,
                {"batch_id": batch_id},
            )

            cursor.execute(
                """
                INSERT INTO bi_schema.dim_location (city, district)
                SELECT DISTINCT city, district
                FROM clean.clean_listings src
                WHERE batch_id = %(batch_id)s
                  AND NOT EXISTS (
                      SELECT 1
                      FROM bi_schema.dim_location dim
                      WHERE dim.city IS NOT DISTINCT FROM src.city
                        AND dim.district IS NOT DISTINCT FROM src.district
                  );
                """,
                {"batch_id": batch_id},
            )

            cursor.execute(
                "DELETE FROM bi_schema.fact_listing WHERE batch_id = %(batch_id)s;",
                {"batch_id": batch_id},
            )

            cursor.execute(
                """
                INSERT INTO bi_schema.fact_listing (
                    time_id, location_id, price, property_type, listing_type,
                    surface_m2, price_per_m2, listing_url, batch_id
                )
                SELECT
                    dt.time_id,
                    dl.location_id,
                    cl.price,
                    cl.property_type,
                    cl.listing_type,
                    feat.surface_m2,
                    feat.price_per_m2,
                    cl.listing_url,
                    cl.batch_id
                FROM clean.clean_listings cl
                LEFT JOIN clean.clean_listing_features feat
                  ON feat.listing_url = cl.listing_url
                JOIN bi_schema.dim_time dt
                  ON dt.date = cl.scraped_at::date
                JOIN bi_schema.dim_location dl
                  ON dl.city IS NOT DISTINCT FROM cl.city
                 AND dl.district IS NOT DISTINCT FROM cl.district
                WHERE cl.batch_id = %(batch_id)s
                ON CONFLICT (listing_url) DO UPDATE SET
                    time_id = EXCLUDED.time_id,
                    location_id = EXCLUDED.location_id,
                    price = EXCLUDED.price,
                    property_type = EXCLUDED.property_type,
                    listing_type = EXCLUDED.listing_type,
                    surface_m2 = EXCLUDED.surface_m2,
                    price_per_m2 = EXCLUDED.price_per_m2,
                    batch_id = EXCLUDED.batch_id;
                """,
                {"batch_id": batch_id},
            )

            cursor.execute(
                "SELECT COUNT(*) AS count FROM bi_schema.fact_listing WHERE batch_id = %(batch_id)s;",
                {"batch_id": batch_id},
            )
            loaded_count = cursor.fetchone()["count"]
        connection.commit()

    log_event(logger, logging.INFO, "bi_schema_loaded", batch_id=batch_id, rows=loaded_count)
    return int(loaded_count)
