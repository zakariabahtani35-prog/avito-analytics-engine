from __future__ import annotations

import logging

from src.utils.db import get_connection
from src.utils.logger import get_logger, log_event


def load_ml_schema(batch_id: str) -> int:
    """Build a dense sale-only OBT for downstream price modeling."""

    logger = get_logger(__name__)
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "DELETE FROM ml_schema.ml_property_features WHERE batch_id = %(batch_id)s;",
                {"batch_id": batch_id},
            )
            cursor.execute(
                """
                WITH sale_features AS (
                    SELECT
                        cl.listing_url,
                        cl.price,
                        LN(cl.price) AS log_price,
                        cl.city,
                        cl.district,
                        cl.property_type,
                        cl.listing_type,
                        cl.latitude,
                        cl.longitude,
                        feat.surface_m2,
                        feat.bedrooms,
                        feat.bathrooms,
                        feat.floor,
                        feat.construction_year,
                        feat.property_age,
                        feat.price_per_m2,
                        feat.rooms_total,
                        feat.price_per_room,
                        feat.room_density,
                        feat.luxury_flag,
                        feat.coastal_city,
                        feat.property_age_bucket,
                        feat.surface_x_rooms,
                        feat.bathrooms_per_bedroom,
                        feat.feature_completeness_score,
                        EXTRACT(YEAR FROM cl.scraped_at)::int AS scraped_year,
                        EXTRACT(MONTH FROM cl.scraped_at)::int AS scraped_month,
                        cl.batch_id
                    FROM clean.clean_listings cl
                    JOIN clean.clean_listing_features feat
                      ON feat.listing_url = cl.listing_url
                    WHERE cl.batch_id = %(batch_id)s
                      AND cl.listing_type = 'sale'
                      AND cl.price > 0
                      AND cl.property_type IS NOT NULL
                      AND cl.city IS NOT NULL
                      AND cl.district IS NOT NULL
                      AND feat.surface_m2 IS NOT NULL
                      AND feat.price_per_m2 IS NOT NULL
                      AND COALESCE(feat.feature_completeness_score, 0) >= 0.70
                ),
                city_index AS (
                    SELECT
                        city,
                        PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY price_per_m2) AS city_market_index
                    FROM sale_features
                    GROUP BY city
                ),
                district_index AS (
                    SELECT
                        city,
                        district,
                        PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY price_per_m2) AS district_market_index
                    FROM sale_features
                    GROUP BY city, district
                )
                INSERT INTO ml_schema.ml_property_features (
                    listing_url, price, log_price, city, district, property_type, listing_type,
                    surface_m2, bedrooms, bathrooms, floor, construction_year, property_age,
                    price_per_m2, rooms_total, price_per_room, room_density, luxury_flag,
                    coastal_city, district_market_index, city_market_index, property_age_bucket,
                    surface_x_rooms, bathrooms_per_bedroom, latitude, longitude,
                    feature_completeness_score, scraped_year, scraped_month, batch_id
                )
                SELECT
                    sf.listing_url,
                    sf.price,
                    sf.log_price,
                    sf.city,
                    sf.district,
                    sf.property_type,
                    sf.listing_type,
                    sf.surface_m2,
                    sf.bedrooms,
                    sf.bathrooms,
                    sf.floor,
                    sf.construction_year,
                    sf.property_age,
                    sf.price_per_m2,
                    sf.rooms_total,
                    sf.price_per_room,
                    sf.room_density,
                    sf.luxury_flag,
                    sf.coastal_city,
                    di.district_market_index,
                    ci.city_market_index,
                    sf.property_age_bucket,
                    sf.surface_x_rooms,
                    sf.bathrooms_per_bedroom,
                    sf.latitude,
                    sf.longitude,
                    sf.feature_completeness_score,
                    sf.scraped_year,
                    sf.scraped_month,
                    sf.batch_id
                FROM sale_features sf
                LEFT JOIN city_index ci
                  ON ci.city = sf.city
                LEFT JOIN district_index di
                  ON di.city = sf.city
                 AND di.district = sf.district
                ON CONFLICT (listing_url) DO UPDATE SET
                    price = EXCLUDED.price,
                    log_price = EXCLUDED.log_price,
                    city = EXCLUDED.city,
                    district = EXCLUDED.district,
                    property_type = EXCLUDED.property_type,
                    listing_type = EXCLUDED.listing_type,
                    surface_m2 = EXCLUDED.surface_m2,
                    bedrooms = EXCLUDED.bedrooms,
                    bathrooms = EXCLUDED.bathrooms,
                    floor = EXCLUDED.floor,
                    construction_year = EXCLUDED.construction_year,
                    property_age = EXCLUDED.property_age,
                    price_per_m2 = EXCLUDED.price_per_m2,
                    rooms_total = EXCLUDED.rooms_total,
                    price_per_room = EXCLUDED.price_per_room,
                    room_density = EXCLUDED.room_density,
                    luxury_flag = EXCLUDED.luxury_flag,
                    coastal_city = EXCLUDED.coastal_city,
                    district_market_index = EXCLUDED.district_market_index,
                    city_market_index = EXCLUDED.city_market_index,
                    property_age_bucket = EXCLUDED.property_age_bucket,
                    surface_x_rooms = EXCLUDED.surface_x_rooms,
                    bathrooms_per_bedroom = EXCLUDED.bathrooms_per_bedroom,
                    latitude = EXCLUDED.latitude,
                    longitude = EXCLUDED.longitude,
                    feature_completeness_score = EXCLUDED.feature_completeness_score,
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

    log_event(logger, logging.INFO, "ml_schema_loaded", batch_id=batch_id, rows=loaded_count)
    return int(loaded_count)
