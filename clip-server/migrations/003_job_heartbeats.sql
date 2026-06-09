-- Add worker heartbeat / attempt tracking for automatic stale-job recovery.
-- Run once:  psql "$DATABASE_URL" -f migrations/003_job_heartbeats.sql

ALTER TABLE jobs ADD COLUMN IF NOT EXISTS heartbeat_at TIMESTAMPTZ;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS attempt_count INTEGER NOT NULL DEFAULT 0;

CREATE INDEX IF NOT EXISTS idx_jobs_running_heartbeat
    ON jobs (status, heartbeat_at)
    WHERE status = 'running';
