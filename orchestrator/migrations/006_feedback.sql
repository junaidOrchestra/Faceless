-- User feedback: suggestions, improvements, bug reports, and praise.
-- Run once:  psql "$DATABASE_URL" -f migrations/006_feedback.sql
--
-- Append-only: every submission is a row we triage later. Keyed by the Supabase
-- user id (the submitter). `email` is an optional reply-to; `page`/`user_agent`
-- are best-effort context to help us reproduce and prioritize.
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
