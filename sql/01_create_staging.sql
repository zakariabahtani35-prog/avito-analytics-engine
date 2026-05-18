CREATE SCHEMA IF NOT EXISTS staging;

CREATE TABLE IF NOT EXISTS staging.raw_listings (
    id SERIAL PRIMARY KEY,
    listing_title_raw TEXT,
    description_raw TEXT,
    price_raw TEXT,
    city_raw TEXT,
    district_raw TEXT,
    property_type_raw TEXT,
    listing_type_raw TEXT,
    surface_raw TEXT,
    bedrooms_raw TEXT,
    bathrooms_raw TEXT,
    floor_raw TEXT,
    latitude_raw TEXT,
    longitude_raw TEXT,
    construction_year_raw TEXT,
    attributes_raw TEXT,
    listing_url TEXT,
    scraped_at TIMESTAMP,
    batch_id TEXT,
    source TEXT,
    detail_scraped BOOLEAN DEFAULT FALSE
);

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'staging' AND table_name = 'raw_listings' AND column_name = 'listing_title'
    ) AND NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'staging' AND table_name = 'raw_listings' AND column_name = 'listing_title_raw'
    ) THEN
        ALTER TABLE staging.raw_listings RENAME COLUMN listing_title TO listing_title_raw;
    END IF;

    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'staging' AND table_name = 'raw_listings' AND column_name = 'price'
    ) AND NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'staging' AND table_name = 'raw_listings' AND column_name = 'price_raw'
    ) THEN
        ALTER TABLE staging.raw_listings RENAME COLUMN price TO price_raw;
    END IF;

    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'staging' AND table_name = 'raw_listings' AND column_name = 'city'
    ) AND NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'staging' AND table_name = 'raw_listings' AND column_name = 'city_raw'
    ) THEN
        ALTER TABLE staging.raw_listings RENAME COLUMN city TO city_raw;
    END IF;

    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'staging' AND table_name = 'raw_listings' AND column_name = 'district'
    ) AND NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'staging' AND table_name = 'raw_listings' AND column_name = 'district_raw'
    ) THEN
        ALTER TABLE staging.raw_listings RENAME COLUMN district TO district_raw;
    END IF;

    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'staging' AND table_name = 'raw_listings' AND column_name = 'surface_m2'
    ) AND NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'staging' AND table_name = 'raw_listings' AND column_name = 'surface_raw'
    ) THEN
        ALTER TABLE staging.raw_listings RENAME COLUMN surface_m2 TO surface_raw;
    END IF;

    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'staging' AND table_name = 'raw_listings' AND column_name = 'bedrooms'
    ) AND NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'staging' AND table_name = 'raw_listings' AND column_name = 'bedrooms_raw'
    ) THEN
        ALTER TABLE staging.raw_listings RENAME COLUMN bedrooms TO bedrooms_raw;
    END IF;

    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'staging' AND table_name = 'raw_listings' AND column_name = 'bathrooms'
    ) AND NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'staging' AND table_name = 'raw_listings' AND column_name = 'bathrooms_raw'
    ) THEN
        ALTER TABLE staging.raw_listings RENAME COLUMN bathrooms TO bathrooms_raw;
    END IF;

    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'staging' AND table_name = 'raw_listings' AND column_name = 'floor'
    ) AND NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'staging' AND table_name = 'raw_listings' AND column_name = 'floor_raw'
    ) THEN
        ALTER TABLE staging.raw_listings RENAME COLUMN floor TO floor_raw;
    END IF;

    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'staging' AND table_name = 'raw_listings' AND column_name = 'construction_year'
    ) AND NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'staging' AND table_name = 'raw_listings' AND column_name = 'construction_year_raw'
    ) THEN
        ALTER TABLE staging.raw_listings RENAME COLUMN construction_year TO construction_year_raw;
    END IF;
END $$;

ALTER TABLE staging.raw_listings
    ADD COLUMN IF NOT EXISTS listing_title_raw TEXT,
    ADD COLUMN IF NOT EXISTS description_raw TEXT,
    ADD COLUMN IF NOT EXISTS price_raw TEXT,
    ADD COLUMN IF NOT EXISTS city_raw TEXT,
    ADD COLUMN IF NOT EXISTS district_raw TEXT,
    ADD COLUMN IF NOT EXISTS property_type_raw TEXT,
    ADD COLUMN IF NOT EXISTS listing_type_raw TEXT,
    ADD COLUMN IF NOT EXISTS surface_raw TEXT,
    ADD COLUMN IF NOT EXISTS bedrooms_raw TEXT,
    ADD COLUMN IF NOT EXISTS bathrooms_raw TEXT,
    ADD COLUMN IF NOT EXISTS floor_raw TEXT,
    ADD COLUMN IF NOT EXISTS latitude_raw TEXT,
    ADD COLUMN IF NOT EXISTS longitude_raw TEXT,
    ADD COLUMN IF NOT EXISTS construction_year_raw TEXT,
    ADD COLUMN IF NOT EXISTS attributes_raw TEXT,
    ADD COLUMN IF NOT EXISTS listing_url TEXT,
    ADD COLUMN IF NOT EXISTS scraped_at TIMESTAMP,
    ADD COLUMN IF NOT EXISTS batch_id TEXT,
    ADD COLUMN IF NOT EXISTS source TEXT,
    ADD COLUMN IF NOT EXISTS detail_scraped BOOLEAN DEFAULT FALSE;

CREATE UNIQUE INDEX IF NOT EXISTS ux_raw_listings_listing_url
    ON staging.raw_listings (listing_url);

CREATE INDEX IF NOT EXISTS idx_raw_listings_batch_id
    ON staging.raw_listings (batch_id);

CREATE INDEX IF NOT EXISTS idx_raw_listings_scraped_at
    ON staging.raw_listings (scraped_at);
