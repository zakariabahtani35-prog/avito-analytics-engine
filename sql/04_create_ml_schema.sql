CREATE SCHEMA IF NOT EXISTS ml_schema;

CREATE TABLE IF NOT EXISTS ml_schema.ml_property_features (
    listing_url TEXT PRIMARY KEY,
    price NUMERIC,
    city TEXT,
    district TEXT,
    surface_m2 NUMERIC,
    bedrooms INTEGER,
    bathrooms INTEGER,
    floor INTEGER,
    price_per_m2 NUMERIC,
    scraped_year INTEGER,
    scraped_month INTEGER,
    batch_id TEXT
);

ALTER TABLE ml_schema.ml_property_features
    ADD COLUMN IF NOT EXISTS price NUMERIC,
    ADD COLUMN IF NOT EXISTS city TEXT,
    ADD COLUMN IF NOT EXISTS district TEXT,
    ADD COLUMN IF NOT EXISTS surface_m2 NUMERIC,
    ADD COLUMN IF NOT EXISTS bedrooms INTEGER,
    ADD COLUMN IF NOT EXISTS bathrooms INTEGER,
    ADD COLUMN IF NOT EXISTS floor INTEGER,
    ADD COLUMN IF NOT EXISTS price_per_m2 NUMERIC,
    ADD COLUMN IF NOT EXISTS scraped_year INTEGER,
    ADD COLUMN IF NOT EXISTS scraped_month INTEGER,
    ADD COLUMN IF NOT EXISTS batch_id TEXT;

ALTER TABLE ml_schema.ml_property_features
    DROP COLUMN IF EXISTS construction_year,
    DROP COLUMN IF EXISTS property_age;

CREATE INDEX IF NOT EXISTS idx_ml_property_features_batch_id
    ON ml_schema.ml_property_features (batch_id);

CREATE INDEX IF NOT EXISTS idx_ml_property_features_city_district
    ON ml_schema.ml_property_features (city, district);

CREATE UNIQUE INDEX IF NOT EXISTS ux_ml_property_features_listing_url
    ON ml_schema.ml_property_features (listing_url);

DO $$
BEGIN
    ALTER TABLE ml_schema.ml_property_features
        DROP CONSTRAINT IF EXISTS chk_ml_property_features_complete;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'chk_ml_property_features_complete'
          AND conrelid = 'ml_schema.ml_property_features'::regclass
    ) THEN
        ALTER TABLE ml_schema.ml_property_features
            ADD CONSTRAINT chk_ml_property_features_complete
            CHECK (
                listing_url IS NOT NULL
                AND price IS NOT NULL
                AND city IS NOT NULL
                AND district IS NOT NULL
                AND scraped_year IS NOT NULL
                AND scraped_month IS NOT NULL
                AND batch_id IS NOT NULL
                AND (surface_m2 IS NULL OR surface_m2 BETWEEN 10 AND 2000)
                AND (bedrooms IS NULL OR bedrooms BETWEEN 0 AND 20)
                AND (bathrooms IS NULL OR bathrooms BETWEEN 0 AND 20)
                AND (floor IS NULL OR floor BETWEEN 0 AND 60)
                AND (price_per_m2 IS NULL OR price_per_m2 BETWEEN 100 AND 100000)
            ) NOT VALID;
    END IF;
END $$;
