-- User accounts, project ownership, tiers, and credits.
-- Run once:  psql "$DATABASE_URL" -f migrations/005_users_projects_credits.sql
--
-- All app data lives in our own Postgres, keyed by the Supabase user id (the
-- JWT `sub`, a UUID). Supabase is used for authentication only; no app tables
-- live there and no Supabase RLS is relied upon for these.

-- Users mirror: identity copied from the Supabase token claims, plus all
-- app-owned state (tier + credit balance). `credits` is the running balance
-- kept in sync with the append-only credit_transactions ledger.
CREATE TABLE IF NOT EXISTS users (
    id                  VARCHAR(64) PRIMARY KEY,            -- Supabase sub (UUID)
    email               TEXT,
    name                TEXT,
    tier                VARCHAR(32) NOT NULL DEFAULT 'free',
    credits             INTEGER NOT NULL DEFAULT 0,
    credits_granted_at  TIMESTAMPTZ,
    stripe_customer_id  TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT users_tier_check CHECK (tier IN ('free', 'individual', 'professional'))
);

-- Projects: one row per video, owned by a user.
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

-- Append-only credit ledger. Each render writes a -spend (and a +refund on
-- failure); grants write +grant. users.credits is the materialized balance.
CREATE TABLE IF NOT EXISTS credit_transactions (
    id          BIGSERIAL PRIMARY KEY,
    user_id     VARCHAR(64) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    delta       INTEGER NOT NULL,
    reason      VARCHAR(64) NOT NULL,
    project_id  VARCHAR(64),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_credit_tx_user ON credit_transactions (user_id, created_at DESC);
-- Idempotency guard for per-project refunds (at most one refund per project).
CREATE UNIQUE INDEX IF NOT EXISTS uq_credit_tx_refund_per_project
    ON credit_transactions (project_id)
    WHERE reason = 'refund' AND project_id IS NOT NULL;

-- Link existing video_jobs to their owner + project.
ALTER TABLE video_jobs ADD COLUMN IF NOT EXISTS owner_id   VARCHAR(64);
ALTER TABLE video_jobs ADD COLUMN IF NOT EXISTS project_id VARCHAR(64);

CREATE INDEX IF NOT EXISTS idx_video_jobs_owner ON video_jobs (owner_id, created_at DESC);
