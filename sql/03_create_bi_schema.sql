CREATE SCHEMA IF NOT EXISTS bi_schema;

CREATE TABLE IF NOT EXISTS bi_schema.dim_time (
    time_id SERIAL PRIMARY KEY,
    date DATE NOT NULL UNIQUE,
    year INTEGER NOT NULL,
    month INTEGER NOT NULL,
    month_name TEXT NOT NULL,
    quarter INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS bi_schema.dim_location (
    location_id SERIAL PRIMARY KEY,
    city TEXT,
    district TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_dim_location_city_district
    ON bi_schema.dim_location (
        COALESCE(city, ''),
        COALESCE(district, '')
    );

CREATE TABLE IF NOT EXISTS bi_schema.fact_listing (
    listing_fact_id SERIAL PRIMARY KEY,
    time_id INTEGER NOT NULL REFERENCES bi_schema.dim_time(time_id),
    location_id INTEGER NOT NULL REFERENCES bi_schema.dim_location(location_id),
    price NUMERIC NOT NULL,
    listing_url TEXT NOT NULL UNIQUE,
    batch_id TEXT
);

ALTER TABLE bi_schema.fact_listing
    ADD COLUMN IF NOT EXISTS time_id INTEGER,
    ADD COLUMN IF NOT EXISTS location_id INTEGER,
    ADD COLUMN IF NOT EXISTS price NUMERIC,
    ADD COLUMN IF NOT EXISTS listing_url TEXT,
    ADD COLUMN IF NOT EXISTS batch_id TEXT;

ALTER TABLE bi_schema.fact_listing
    DROP COLUMN IF EXISTS property_features_id,
    DROP COLUMN IF EXISTS price_per_m2;

DROP TABLE IF EXISTS bi_schema.dim_property_features;

CREATE INDEX IF NOT EXISTS idx_fact_listing_time_id
    ON bi_schema.fact_listing (time_id);

CREATE INDEX IF NOT EXISTS idx_fact_listing_location_id
    ON bi_schema.fact_listing (location_id);

CREATE UNIQUE INDEX IF NOT EXISTS ux_fact_listing_listing_url
    ON bi_schema.fact_listing (listing_url);

DROP INDEX IF EXISTS idx_fact_listing_property_features_id;

CREATE INDEX IF NOT EXISTS idx_fact_listing_batch_id
    ON bi_schema.fact_listing (batch_id);
