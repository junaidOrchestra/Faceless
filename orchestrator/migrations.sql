CREATE TABLE IF NOT EXISTS video_jobs (
    id VARCHAR(128) PRIMARY KEY,
    user_id VARCHAR(128) NOT NULL,
    status VARCHAR(16) NOT NULL DEFAULT 'queued',
    progress VARCHAR(64),
    result_url TEXT,
    error TEXT,
    audio_path TEXT,
    payload JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_video_jobs_status ON video_jobs (status, created_at);

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
    preview_url TEXT,
    kind VARCHAR(16),
    score DOUBLE PRECISION,
    attribution TEXT,
    candidates JSONB,
    PRIMARY KEY (video_job_id, beat_index)
);
