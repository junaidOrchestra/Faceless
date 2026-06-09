-- Align an existing orchestrator DB with the current minimal schema.
-- Run once:  psql "$DATABASE_URL" -f migrations/002_minimize_schema.sql
--
-- Drops three video_jobs columns that no application logic reads:
--   * clip_job_id  -> deterministic (<job_id>-clip), reconstructed each run
--   * claimed_at   -> no reader left after the Redis dispatch migration
--   * updated_at   -> never read or returned
-- (user_id is intentionally kept.)
--
-- The beats / beat_assignments tables are kept (they power
-- GET /videos/{id}/beats); they are (re)created here idempotently so this file
-- is safe on a fresh or partially-migrated database.

ALTER TABLE video_jobs DROP COLUMN IF EXISTS clip_job_id;
ALTER TABLE video_jobs DROP COLUMN IF EXISTS claimed_at;
ALTER TABLE video_jobs DROP COLUMN IF EXISTS updated_at;

CREATE TABLE IF NOT EXISTS beats (
    video_job_id VARCHAR(128) NOT NULL REFERENCES video_jobs(id) ON DELETE CASCADE,
    index INTEGER NOT NULL,
    text TEXT NOT NULL,
    start_s DOUBLE PRECISION NOT NULL,
    end_s DOUBLE PRECISION NOT NULL,
    queries JSONB,
    PRIMARY KEY (video_job_id, index)
);

CREATE TABLE IF NOT EXISTS beat_assignments (
    video_job_id VARCHAR(128) NOT NULL REFERENCES video_jobs(id) ON DELETE CASCADE,
    beat_index INTEGER NOT NULL,
    platform VARCHAR(64),
    media_url TEXT,
    kind VARCHAR(16),
    score DOUBLE PRECISION,
    attribution TEXT,
    PRIMARY KEY (video_job_id, beat_index)
);

DATABASE_URL ''
