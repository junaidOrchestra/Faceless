# Supabase Auth + Accounts Setup

Manual steps in the **Supabase dashboard** before the app can authenticate users.
App data (users mirror, projects, tiers, credits) lives in **your own Postgres**,
keyed by the Supabase user id (JWT `sub`). Supabase is used for **authentication
only** — no app tables in Supabase and no Supabase RLS for them.

---

## 1. Create a Supabase project

1. Go to [https://supabase.com/dashboard](https://supabase.com/dashboard) → **New project**.
2. Pick a region close to your orchestrator and Postgres.
3. Set a strong database password (for Supabase's internal auth DB — **not** your app Postgres).

---

## 2. Enable auth providers

**Authentication → Providers**

### Email

- Enable **Email** provider.
- For local dev you may disable “Confirm email” under **Authentication → Providers → Email**
  to skip inbox verification (leave it **on** in production).

### Google

1. In [Google Cloud Console](https://console.cloud.google.com/) create an **OAuth 2.0 Client ID**
   (Web application).
2. Add **Authorized redirect URIs**:
   - `https://<YOUR-PROJECT-REF>.supabase.co/auth/v1/callback`
3. Copy the **Client ID** and **Client secret** into Supabase:
   **Authentication → Providers → Google** → enable and paste credentials.

---

## 3. Site URL and redirect URLs

**Authentication → URL Configuration**

| Setting | Example (local) | Example (production) |
|--------|-------------------|----------------------|
| **Site URL** | `http://localhost:3000` | `https://yourdomain.com` |
| **Redirect URLs** | `http://localhost:3000/auth/callback` | `https://yourdomain.com/auth/callback` |

Add any preview/staging URLs you use (Vercel preview domains, etc.).

---

## 4. Copy credentials into env

**Project Settings → API**

| Dashboard value | Env var | Where |
|----------------|---------|--------|
| Project URL | `NEXT_PUBLIC_SUPABASE_URL` | Frontend (public) |
| anon / public key | `NEXT_PUBLIC_SUPABASE_ANON_KEY` | Frontend (public) |
| service_role key | `SUPABASE_SERVICE_ROLE_KEY` | **Server only** (Next.js; never expose to browser) |
| JWT Secret (under JWT Settings) | `SUPABASE_JWT_SECRET` | Orchestrator (FastAPI) |

Also set on the orchestrator:

- `SUPABASE_URL` — same as Project URL (used to derive JWKS if you switch to asymmetric signing).

---

## 5. Run app database migrations (your Postgres)

The orchestrator stores users, projects, credits, and links `video_jobs` to owners.
Apply migrations against **your** Postgres (Neon, RDS, docker-compose `db`, etc.) — **not** Supabase's DB.

```bash
cd orchestrator

# Fresh database (creates everything):
psql "$DATABASE_URL" -f migrations.sql

# Existing database (incremental):
psql "$DATABASE_URL" -f migrations/005_users_projects_credits.sql
```

Use the async SQLAlchemy URL form:

`postgresql+psycopg://user:password@host:5432/dbname`

(`psql` itself uses `postgresql://…` without the `+psycopg` suffix.)

---

## 6. Install dependencies

```bash
# Orchestrator
cd orchestrator && pip install -r requirements.txt

# Frontend
cd seemless && npm install
```

---

## 7. Smoke test

1. Start Postgres + Redis + orchestrator + frontend.
2. Sign up at `/signup` (or “Continue with Google”).
3. Confirm `/api/me` returns your tier + credit balance.
4. Upload narration → render → download only works while signed in as the owner.

---

## Notes

- **Clip server** stays user-agnostic; orchestrator → clip-server uses `CLIP_SERVER_SECRET`
  (`X-API-Key` / bearer), not the user JWT.
- **Stripe** (`STRIPE_*`) is intentionally left as TODO for paid upgrades / credit packs.
- **Result videos** are never returned as public URLs in JSON; owners fetch via
  `GET /videos/{id}/download`, which checks ownership and returns a **short-lived presigned**
  Backblaze B2 URL (or streams locally when `STORAGE_LOCAL=true`).
