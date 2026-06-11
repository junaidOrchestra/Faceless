-- User-added standalone "animated text" beats (text cards with a controllable
-- writing speed) that are NOT backed by narration audio.
-- Run once:  psql "$DATABASE_URL" -f migrations/009_beat_inserts.sql
--
-- ``kind`` distinguishes a normal transcript beat ("narration") from a user-added
-- standalone card ("insert"). An insert contributes ``duration_s`` seconds of
-- video plus an equal SILENT gap in the muxed narration (its own per-word SFX is
-- mixed on top), so total audio length keeps matching total video length.
-- Both columns are added with safe defaults so existing jobs keep working.
ALTER TABLE beats
    ADD COLUMN IF NOT EXISTS kind VARCHAR(16) NOT NULL DEFAULT 'narration';

ALTER TABLE beats
    ADD COLUMN IF NOT EXISTS duration_s DOUBLE PRECISION;
