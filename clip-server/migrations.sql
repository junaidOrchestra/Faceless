-- CLIP server schema (run against the clip database).
-- Requires pgvector >= 0.5.0 for the HNSW index (Neon/Supabase/pgvector image OK).
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS jobs (
    job_id VARCHAR(128) PRIMARY KEY,
    status VARCHAR(16) NOT NULL DEFAULT 'queued',
    items_input JSONB NOT NULL,
    items_result JSONB,
    error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    claimed_at TIMESTAMPTZ,
    heartbeat_at TIMESTAMPTZ,
    attempt_count INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_jobs_status_created ON jobs (status, created_at);
CREATE INDEX IF NOT EXISTS idx_jobs_running_heartbeat
    ON jobs (status, heartbeat_at)
    WHERE status = 'running';

CREATE TABLE IF NOT EXISTS assets (
    asset_id BIGSERIAL PRIMARY KEY,
    platform VARCHAR(64) NOT NULL,
    external_id VARCHAR(256) NOT NULL,
    kind VARCHAR(16) NOT NULL,
    media_url TEXT NOT NULL,
    preview_url TEXT NOT NULL,
    attribution_name VARCHAR(512),
    attribution_url TEXT,
    license VARCHAR(128),
    duration DOUBLE PRECISION,
    embedding vector(512) NOT NULL,
    keyword VARCHAR(256),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_assets_platform_external UNIQUE (platform, external_id)
);

-- Cache-first similarity search: ANN over already-embedded assets, cosine to
-- match CLIP. Embeddings are L2-normalized, so cosine ranking is exact-equivalent
-- to inner product; cosine keeps the math obvious. Powers search_cached_assets().
CREATE INDEX IF NOT EXISTS idx_assets_embedding
    ON assets USING hnsw (embedding vector_cosine_ops);
