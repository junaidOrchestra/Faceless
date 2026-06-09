-- Add worker heartbeat / attempt tracking for automatic stale-job recovery.
-- Run once:  psql "$DATABASE_URL" -f migrations/004_job_heartbeats.sql
--
-- Active jobs now record which attempt is running and when its worker last
-- proved liveness. A periodic sweeper requeues stale active jobs or fails them
-- after max attempts, so mid-process worker deaths no longer require a service
-- restart to recover.

ALTER TABLE video_jobs ADD COLUMN IF NOT EXISTS claimed_at TIMESTAMPTZ;
ALTER TABLE video_jobs ADD COLUMN IF NOT EXISTS heartbeat_at TIMESTAMPTZ;
ALTER TABLE video_jobs ADD COLUMN IF NOT EXISTS attempt_count INTEGER NOT NULL DEFAULT 0;

CREATE INDEX IF NOT EXISTS idx_video_jobs_active_heartbeat
    ON video_jobs (status, heartbeat_at)
    WHERE status IN ('transcribing', 'llm', 'rendering');
