-- Per-word timing on beats, powering "tighten audio" (filler-word removal and
-- accurate caption timing).
-- Run once:  psql "$DATABASE_URL" -f migrations/008_beat_words.sql
--
-- Each row is a JSON array of {"t": text, "s": start_s, "e": end_s, "f": is_filler}.
-- Nullable so jobs transcribed before this column still load (they simply have no
-- word-level data and the tighten-audio options are no-ops for them).
ALTER TABLE beats
    ADD COLUMN IF NOT EXISTS words JSONB;
