-- Users mirror keyed by the Supabase user id (JWT `sub`). Supabase is used for
-- authentication only; all app data (tier, credits) lives here.
CREATE TABLE IF NOT EXISTS users (
    id                  VARCHAR(64) PRIMARY KEY,
    email               TEXT,
    name                TEXT,
    tier                VARCHAR(32) NOT NULL DEFAULT 'free',
    credits             INTEGER NOT NULL DEFAULT 0,
    credits_granted_at  TIMESTAMPTZ,
    stripe_customer_id  TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    -- 'admin' is an internal-only tier (not advertised); assign it by updating
    -- the row directly. Unlimited credits/length but watermark stays on.
    CONSTRAINT users_tier_check CHECK (tier IN ('free', 'individual', 'professional', 'admin'))
);

CREATE TABLE IF NOT EXISTS projects (
    id          VARCHAR(64) PRIMARY KEY,
    owner_id    VARCHAR(64) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title       TEXT,
    input_type  VARCHAR(32),
    status      VARCHAR(32) NOT NULL DEFAULT 'created',
    result_url  TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT projects_input_type_check CHECK (
        input_type IS NULL OR input_type IN (
            'audio_file', 'audio_record', 'video_file', 'video_record'
        )
    )
);

CREATE INDEX IF NOT EXISTS idx_projects_owner ON projects (owner_id, created_at DESC);

CREATE TABLE IF NOT EXISTS credit_transactions (
    id          BIGSERIAL PRIMARY KEY,
    user_id     VARCHAR(64) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    delta       INTEGER NOT NULL,
    reason      VARCHAR(64) NOT NULL,
    project_id  VARCHAR(64),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_credit_tx_user ON credit_transactions (user_id, created_at DESC);
CREATE UNIQUE INDEX IF NOT EXISTS uq_credit_tx_refund_per_project
    ON credit_transactions (project_id)
    WHERE reason = 'refund' AND project_id IS NOT NULL;

-- Append-only user feedback (suggestions, improvements, bugs, praise).
CREATE TABLE IF NOT EXISTS feedback (
    id          BIGSERIAL PRIMARY KEY,
    user_id     VARCHAR(64) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    category    VARCHAR(32) NOT NULL DEFAULT 'suggestion',
    message     TEXT NOT NULL,
    rating      INTEGER,
    email       TEXT,
    page        TEXT,
    user_agent  TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT feedback_category_check CHECK (
        category IN ('suggestion', 'improvement', 'bug', 'praise', 'other')
    ),
    CONSTRAINT feedback_rating_check CHECK (rating IS NULL OR rating BETWEEN 1 AND 5)
);

CREATE INDEX IF NOT EXISTS idx_feedback_user ON feedback (user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_feedback_recent ON feedback (created_at DESC);

CREATE TABLE IF NOT EXISTS video_jobs (
    id VARCHAR(128) PRIMARY KEY,
    user_id VARCHAR(128) NOT NULL,
    owner_id VARCHAR(64),
    project_id VARCHAR(64),
    status VARCHAR(16) NOT NULL DEFAULT 'queued',
    progress VARCHAR(64),
    result_url TEXT,
    error TEXT,
    audio_path TEXT,
    payload JSONB,
    claimed_at TIMESTAMPTZ,
    heartbeat_at TIMESTAMPTZ,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_video_jobs_status ON video_jobs (status, created_at);
CREATE INDEX IF NOT EXISTS idx_video_jobs_owner ON video_jobs (owner_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_video_jobs_active_heartbeat
    ON video_jobs (status, heartbeat_at)
    WHERE status IN ('transcribing', 'llm', 'rendering');

CREATE TABLE IF NOT EXISTS beats (
    video_job_id VARCHAR(128) NOT NULL REFERENCES video_jobs(id) ON DELETE CASCADE,
    index INTEGER NOT NULL,
    text TEXT NOT NULL,
    start_s DOUBLE PRECISION NOT NULL,
    end_s DOUBLE PRECISION NOT NULL,
    queries JSONB,
    words JSONB,
    -- "narration" (transcript beat) or "insert" (user-added standalone animated
    -- text card with no narration; duration_s seconds of video + a silent gap).
    kind VARCHAR(16) NOT NULL DEFAULT 'narration',
    duration_s DOUBLE PRECISION,
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
