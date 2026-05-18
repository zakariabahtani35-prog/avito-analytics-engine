CREATE SCHEMA IF NOT EXISTS clean;

CREATE TABLE IF NOT EXISTS clean.clean_listings (
    listing_id SERIAL PRIMARY KEY,
    listing_title_clean TEXT NOT NULL,
    description_clean TEXT,
    price NUMERIC NOT NULL,
    city TEXT NOT NULL,
    district TEXT NOT NULL,
    property_type TEXT NOT NULL,
    listing_type TEXT NOT NULL,
    latitude NUMERIC,
    longitude NUMERIC,
    listing_url TEXT NOT NULL,
    scraped_at TIMESTAMP NOT NULL,
    batch_id TEXT NOT NULL
);

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'clean' AND table_name = 'clean_listings' AND column_name = 'listing_title'
    ) AND NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'clean' AND table_name = 'clean_listings' AND column_name = 'listing_title_clean'
    ) THEN
        ALTER TABLE clean.clean_listings RENAME COLUMN listing_title TO listing_title_clean;
    END IF;
END $$;

DO $$
BEGIN
    ALTER TABLE clean.clean_listings
        DROP CONSTRAINT IF EXISTS chk_clean_listings_price_range;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'chk_clean_listings_price_range'
          AND conrelid = 'clean.clean_listings'::regclass
    ) THEN
        ALTER TABLE clean.clean_listings
            ADD CONSTRAINT chk_clean_listings_price_range
            CHECK (price BETWEEN 300 AND 100000000) NOT VALID;
    END IF;
END $$;

ALTER TABLE clean.clean_listings
    ADD COLUMN IF NOT EXISTS listing_title_clean TEXT,
    ADD COLUMN IF NOT EXISTS description_clean TEXT,
    ADD COLUMN IF NOT EXISTS price NUMERIC,
    ADD COLUMN IF NOT EXISTS city TEXT,
    ADD COLUMN IF NOT EXISTS district TEXT,
    ADD COLUMN IF NOT EXISTS property_type TEXT,
    ADD COLUMN IF NOT EXISTS listing_type TEXT,
    ADD COLUMN IF NOT EXISTS latitude NUMERIC,
    ADD COLUMN IF NOT EXISTS longitude NUMERIC,
    ADD COLUMN IF NOT EXISTS listing_url TEXT,
    ADD COLUMN IF NOT EXISTS scraped_at TIMESTAMP,
    ADD COLUMN IF NOT EXISTS batch_id TEXT;

ALTER TABLE clean.clean_listings
    DROP COLUMN IF EXISTS surface_m2,
    DROP COLUMN IF EXISTS bedrooms,
    DROP COLUMN IF EXISTS bathrooms,
    DROP COLUMN IF EXISTS floor,
    DROP COLUMN IF EXISTS construction_year,
    DROP COLUMN IF EXISTS price_per_m2,
    DROP COLUMN IF EXISTS property_age;

DO $$
BEGIN
    IF to_regclass('clean.clean_listing_features') IS NOT NULL THEN
        ALTER TABLE clean.clean_listing_features
            DROP CONSTRAINT IF EXISTS chk_clean_listing_features_complete_realistic;
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'chk_clean_listings_required_present'
          AND conrelid = 'clean.clean_listings'::regclass
    ) THEN
        ALTER TABLE clean.clean_listings
            ADD CONSTRAINT chk_clean_listings_required_present
            CHECK (
                NULLIF(BTRIM(listing_title_clean), '') IS NOT NULL
                AND price IS NOT NULL
                AND NULLIF(BTRIM(city), '') IS NOT NULL
                AND NULLIF(BTRIM(district), '') IS NOT NULL
                AND NULLIF(BTRIM(property_type), '') IS NOT NULL
                AND NULLIF(BTRIM(listing_type), '') IS NOT NULL
                AND listing_type IN ('sale', 'rent')
                AND NULLIF(BTRIM(listing_url), '') IS NOT NULL
                AND scraped_at IS NOT NULL
                AND NULLIF(BTRIM(batch_id), '') IS NOT NULL
                AND (latitude IS NULL OR latitude BETWEEN -90 AND 90)
                AND (longitude IS NULL OR longitude BETWEEN -180 AND 180)
            ) NOT VALID;
    END IF;
END $$;

CREATE UNIQUE INDEX IF NOT EXISTS ux_clean_listings_listing_url
    ON clean.clean_listings (listing_url);

CREATE INDEX IF NOT EXISTS idx_clean_listings_batch_id
    ON clean.clean_listings (batch_id);

CREATE INDEX IF NOT EXISTS idx_clean_listings_city_district
    ON clean.clean_listings (city, district);

DROP INDEX IF EXISTS idx_clean_listings_price_surface;

CREATE TABLE IF NOT EXISTS clean.clean_listing_features (
    listing_url TEXT PRIMARY KEY REFERENCES clean.clean_listings(listing_url) ON DELETE CASCADE,
    surface_m2 NUMERIC,
    bedrooms INTEGER,
    bathrooms INTEGER,
    floor INTEGER,
    construction_year INTEGER,
    property_age INTEGER,
    price_per_m2 NUMERIC,
    rooms_total INTEGER,
    price_per_room NUMERIC,
    room_density NUMERIC,
    luxury_flag INTEGER,
    coastal_city INTEGER,
    property_age_bucket TEXT,
    surface_x_rooms NUMERIC,
    bathrooms_per_bedroom NUMERIC,
    extraction_score NUMERIC,
    feature_completeness_score NUMERIC,
    batch_id TEXT
);

ALTER TABLE clean.clean_listing_features
    ADD COLUMN IF NOT EXISTS listing_url TEXT,
    ADD COLUMN IF NOT EXISTS surface_m2 NUMERIC,
    ADD COLUMN IF NOT EXISTS bedrooms INTEGER,
    ADD COLUMN IF NOT EXISTS bathrooms INTEGER,
    ADD COLUMN IF NOT EXISTS floor INTEGER,
    ADD COLUMN IF NOT EXISTS construction_year INTEGER,
    ADD COLUMN IF NOT EXISTS property_age INTEGER,
    ADD COLUMN IF NOT EXISTS price_per_m2 NUMERIC,
    ADD COLUMN IF NOT EXISTS rooms_total INTEGER,
    ADD COLUMN IF NOT EXISTS price_per_room NUMERIC,
    ADD COLUMN IF NOT EXISTS room_density NUMERIC,
    ADD COLUMN IF NOT EXISTS luxury_flag INTEGER,
    ADD COLUMN IF NOT EXISTS coastal_city INTEGER,
    ADD COLUMN IF NOT EXISTS property_age_bucket TEXT,
    ADD COLUMN IF NOT EXISTS surface_x_rooms NUMERIC,
    ADD COLUMN IF NOT EXISTS bathrooms_per_bedroom NUMERIC,
    ADD COLUMN IF NOT EXISTS extraction_score NUMERIC,
    ADD COLUMN IF NOT EXISTS feature_completeness_score NUMERIC,
    ADD COLUMN IF NOT EXISTS batch_id TEXT;

CREATE INDEX IF NOT EXISTS idx_clean_listing_features_batch_id
    ON clean.clean_listing_features (batch_id);

CREATE UNIQUE INDEX IF NOT EXISTS ux_clean_listing_features_listing_url
    ON clean.clean_listing_features (listing_url);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'chk_clean_listing_features_complete_realistic'
          AND conrelid = 'clean.clean_listing_features'::regclass
    ) THEN
        ALTER TABLE clean.clean_listing_features
            ADD CONSTRAINT chk_clean_listing_features_complete_realistic
            CHECK (
                listing_url IS NOT NULL
                AND (surface_m2 IS NULL OR surface_m2 BETWEEN 10 AND 20000)
                AND (bedrooms IS NULL OR bedrooms BETWEEN 0 AND 20)
                AND (bathrooms IS NULL OR bathrooms BETWEEN 0 AND 20)
                AND (floor IS NULL OR floor BETWEEN 0 AND 60)
                AND (price_per_m2 IS NULL OR price_per_m2 BETWEEN 100 AND 100000)
                AND (construction_year IS NULL OR construction_year BETWEEN 1800 AND 2100)
                AND (property_age IS NULL OR property_age BETWEEN 0 AND 200)
                AND (rooms_total IS NULL OR rooms_total BETWEEN 0 AND 40)
                AND (price_per_room IS NULL OR price_per_room > 0)
                AND (room_density IS NULL OR room_density >= 0)
                AND (luxury_flag IS NULL OR luxury_flag IN (0, 1))
                AND (coastal_city IS NULL OR coastal_city IN (0, 1))
                AND (surface_x_rooms IS NULL OR surface_x_rooms >= 0)
                AND (bathrooms_per_bedroom IS NULL OR bathrooms_per_bedroom >= 0)
                AND (extraction_score IS NULL OR extraction_score BETWEEN 0 AND 1)
                AND (feature_completeness_score IS NULL OR feature_completeness_score BETWEEN 0 AND 1)
            ) NOT VALID;
    END IF;
END $$;
