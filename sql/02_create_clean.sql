CREATE SCHEMA IF NOT EXISTS clean;

CREATE TABLE IF NOT EXISTS clean.clean_listings (
    listing_id SERIAL PRIMARY KEY,
    listing_title_clean TEXT NOT NULL,
    price NUMERIC NOT NULL,
    city TEXT NOT NULL,
    district TEXT NOT NULL,
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
            CHECK (price BETWEEN 10000 AND 50000000) NOT VALID;
    END IF;
END $$;

ALTER TABLE clean.clean_listings
    ADD COLUMN IF NOT EXISTS listing_title_clean TEXT,
    ADD COLUMN IF NOT EXISTS price NUMERIC,
    ADD COLUMN IF NOT EXISTS city TEXT,
    ADD COLUMN IF NOT EXISTS district TEXT,
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
                AND NULLIF(BTRIM(listing_url), '') IS NOT NULL
                AND scraped_at IS NOT NULL
                AND NULLIF(BTRIM(batch_id), '') IS NOT NULL
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
    price_per_m2 NUMERIC,
    batch_id TEXT
);

ALTER TABLE clean.clean_listing_features
    ADD COLUMN IF NOT EXISTS listing_url TEXT,
    ADD COLUMN IF NOT EXISTS surface_m2 NUMERIC,
    ADD COLUMN IF NOT EXISTS bedrooms INTEGER,
    ADD COLUMN IF NOT EXISTS bathrooms INTEGER,
    ADD COLUMN IF NOT EXISTS floor INTEGER,
    ADD COLUMN IF NOT EXISTS price_per_m2 NUMERIC,
    ADD COLUMN IF NOT EXISTS batch_id TEXT;

ALTER TABLE clean.clean_listing_features
    DROP COLUMN IF EXISTS construction_year,
    DROP COLUMN IF EXISTS property_age;

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
                AND (surface_m2 IS NULL OR surface_m2 BETWEEN 10 AND 2000)
                AND (bedrooms IS NULL OR bedrooms BETWEEN 0 AND 20)
                AND (bathrooms IS NULL OR bathrooms BETWEEN 0 AND 20)
                AND (floor IS NULL OR floor BETWEEN 0 AND 60)
                AND (price_per_m2 IS NULL OR price_per_m2 BETWEEN 100 AND 100000)
            ) NOT VALID;
    END IF;
END $$;
