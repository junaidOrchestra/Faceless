-- Allow the internal-only 'admin' tier on users.tier.
-- Run once:  psql "$DATABASE_URL" -f migrations/007_admin_tier.sql
--
-- 'admin' is never advertised and has no self-serve path. Promote an account
-- out-of-band, e.g.:
--   UPDATE users SET tier = 'admin' WHERE email = 'you@example.com';
-- It grants unlimited credits and no length limit, but keeps the watermark on.
ALTER TABLE users DROP CONSTRAINT IF EXISTS users_tier_check;
ALTER TABLE users
    ADD CONSTRAINT users_tier_check
    CHECK (tier IN ('free', 'individual', 'professional', 'admin'));
