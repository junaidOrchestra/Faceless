-- Uploaded narration / source footage metadata (direct-to-B2 uploads).
CREATE TABLE IF NOT EXISTS source_videos (
    id              VARCHAR(128) PRIMARY KEY,
    owner_id        VARCHAR(64)  NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    video_job_id    VARCHAR(128) REFERENCES video_jobs(id) ON DELETE SET NULL,
    r2_key          TEXT         NOT NULL,
    filename        TEXT,
    content_type    VARCHAR(128),
    size_bytes      BIGINT,
    status          VARCHAR(32)  NOT NULL DEFAULT 'uploaded',
    duration_s      DOUBLE PRECISION,
    width           INTEGER,
    height          INTEGER,
    fps             DOUBLE PRECISION,
    video_codec     VARCHAR(64),
    audio_codec     VARCHAR(64),
    error           TEXT,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS source_videos_owner_idx
    ON source_videos (owner_id, created_at DESC);

CREATE INDEX IF NOT EXISTS source_videos_job_idx
    ON source_videos (video_job_id)
    WHERE video_job_id IS NOT NULL;
