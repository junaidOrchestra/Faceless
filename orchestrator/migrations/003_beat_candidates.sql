-- Add per-beat candidate options to an existing orchestrator DB.
-- Run once:  psql "$DATABASE_URL" -f migrations/003_beat_candidates.sql
--
-- Adds two columns to beat_assignments so GET /videos/{id}/beats can return the
-- preview/media URLs for the selected clip plus a couple of alternates:
--   * preview_url -> preview image of the selected clip
--   * candidates  -> JSON list of ranked options (selected first, then alternates),
--                    each with platform/kind/media_url/preview_url/score/selected
-- Safe to re-run (IF NOT EXISTS).

ALTER TABLE beat_assignments ADD COLUMN IF NOT EXISTS preview_url TEXT;
ALTER TABLE beat_assignments ADD COLUMN IF NOT EXISTS candidates JSONB;
