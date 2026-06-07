-- Ensure the assets cache has the unique constraint required for safe upserts.
--
-- Older databases may have been created with an auto-named UNIQUE constraint
-- from `UNIQUE (platform, external_id)`. The application now targets the columns
-- directly, but keeping the canonical constraint name makes the live schema match
-- the ORM model and fresh `migrations.sql`.

DO $$
DECLARE
    existing_name text;
BEGIN
    SELECT conname
    INTO existing_name
    FROM pg_constraint
    WHERE conrelid = 'assets'::regclass
      AND contype = 'u'
      AND conkey = ARRAY[
          (SELECT attnum FROM pg_attribute WHERE attrelid = 'assets'::regclass AND attname = 'platform'),
          (SELECT attnum FROM pg_attribute WHERE attrelid = 'assets'::regclass AND attname = 'external_id')
      ]::smallint[];

    IF existing_name IS NULL THEN
        ALTER TABLE assets
            ADD CONSTRAINT uq_assets_platform_external UNIQUE (platform, external_id);
    ELSIF existing_name <> 'uq_assets_platform_external' THEN
        EXECUTE format(
            'ALTER TABLE assets RENAME CONSTRAINT %I TO uq_assets_platform_external',
            existing_name
        );
    END IF;
END $$;
