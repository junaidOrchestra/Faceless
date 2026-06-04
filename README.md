# Faceless Video — narration audio → narrated faceless video

A two-service Python system that turns a narration **audio file** into a narrated
**"faceless" video** (stock footage / photos cut to the narration, with Ken Burns
pans, trimmed clips, and text cards for rhetorical beats).

It is split into two independently deployable FastAPI services that talk **only
over HTTP**, each owning its own Postgres database.

```
            audio                         keywords (batch)
 client ──────────────▶  ORCHESTRATOR  ─────────────────────▶  CLIP SERVER
            video  ◀──────  (the brain)  ◀─────────────────────  (the finder)
                                          ranked assets (batch)
```

## The two tiers

### 1. Orchestrator — *the brain* (beat / video aware)
`orchestrator/` — receives audio, transcribes it into **beats**, asks an LLM for
per-beat **search keywords**, calls the CLIP server to find media, assembles a
**timeline**, and renders the **video** with FFmpeg. It is the only service that
knows what a beat, a timeline, or a video is.

### 2. CLIP server — *the finder* (beat **agnostic**)
`clip-server/` — a generic **"keywords → ranked assets"** primitive. Given a batch
of keywords it searches configurable stock sources (Pexels photos/videos,
Wikimedia), embeds the previews with **CLIP**, ranks them by cosine similarity to
the keyword, and returns assets. It knows nothing about audio, beats, videos, or
rendering — it could be reused by any application that needs ranked media.

## The async submit-poll boundary

Both services use the **same durable, async, submit-then-poll** contract so they
survive free-tier host restarts (no in-memory job state — everything in Postgres):

1. `POST /jobs` (or `/videos`) with a client-supplied `job_id` → `202 {job_id}`
   (idempotent: resubmitting the same id returns the existing job).
2. An in-process **background worker** claims `queued` jobs from Postgres, runs the
   pipeline, and writes results back to Postgres. Jobs stuck in `running` past a
   timeout are re-queued (`claimed_at` watchdog).
3. `GET /jobs/{id}` returns `{status: queued|running|done|failed, ...}`; when
   `done` the results are embedded in the response. The orchestrator polls the
   CLIP server with backoff, branching on **status** (never on result presence).

## Repository layout

```
README.md              ← you are here (architecture + how to run both)
docker-compose.yml     ← local dev: pgvector Postgres + both services
infra/init-db.sql      ← creates the two local databases
clip-server/           ← the finder (HF Spaces target, CPU, port 7860)
orchestrator/          ← the brain  (FFmpeg + whisper, port 8000)
```

Each service is self-contained: its own `app/`, `Dockerfile`, `requirements.txt`,
`migrations.sql`, `.env.example`, `README.md`, and `tests/`. There is **no shared
runtime package** — the CLIP request/response models are intentionally duplicated
in the orchestrator's `ClipClient` (loose coupling over DRY across a network seam).

## Run everything locally (docker-compose)

```bash
# 1. Build and start Postgres (pgvector) + both services.
docker compose up --build

# 2. Apply migrations once the DB is healthy (creates extension + tables).
docker compose exec -T db psql -U faceless -d clip         < clip-server/migrations.sql
docker compose exec -T db psql -U faceless -d orchestrator < orchestrator/migrations.sql
```

Then:

- CLIP server docs:   http://localhost:7860/docs
- Orchestrator docs:  http://localhost:8000/docs

Health checks (no auth): `GET http://localhost:7860/health`,
`GET http://localhost:8000/health`.

All other routes require a bearer token equal to that service's
`API_AUTH_SECRET` (see each `.env.example`):

```bash
curl -H "Authorization: Bearer dev-orch-secret" \
     -F "audio=@narration.mp3" \
     http://localhost:8000/videos
```

## Environment variables (overview)

See each service's `.env.example` for the authoritative list (names only).

| Variable                         | Service       | Purpose                                   |
| -------------------------------- | ------------- | ----------------------------------------- |
| `DATABASE_URL`                   | both          | `postgresql+psycopg://…` async URL        |
| `API_AUTH_SECRET`                | both          | bearer token for protected routes         |
| `ENABLED_SOURCES`                | clip-server   | JSON list of default stock sources        |
| `CLIP_MODEL_NAME`                | clip-server   | sentence-transformers CLIP model id       |
| `CLIP_SERVER_URL`                | orchestrator  | base URL of the CLIP server               |
| `CLIP_SERVER_SECRET`             | orchestrator  | bearer token to call the CLIP server      |
| `LLM_PROVIDER`                   | orchestrator  | `gemini` or `local`                       |
| `GEMINI_API_KEY`                 | orchestrator  | key for the Gemini provider               |
| `LOCAL_LLM_MODEL_PATH`           | orchestrator  | GGUF path for the local llama provider    |
| `ALLOWED_ORIGINS`                | orchestrator  | JSON list of CORS origins                 |

API keys for stock sources (Pexels) are **never** read from env on the CLIP
server — they arrive per-request in the body, are used in memory only, and are
never logged or persisted.

## Tests

Each service ships a pytest smoke test that runs the full submit→poll→done loop
against a real pgvector Postgres using **stub** sources / models (no model
downloads, no network):

```bash
# Start just the database, then run each service's tests.
docker compose up -d db
docker compose exec -T db psql -U faceless -d clip         < clip-server/migrations.sql
docker compose exec -T db psql -U faceless -d orchestrator < orchestrator/migrations.sql

cd clip-server   && pip install -r requirements.txt && pytest && cd ..
cd orchestrator  && pip install -r requirements.txt && pytest && cd ..
```

## Deploy notes

- **CLIP server → Hugging Face Spaces** (Docker SDK, CPU, port 7860, 16 GB). The
  Dockerfile pre-downloads the CLIP model at build time and runs as a non-root
  user. See `clip-server/README.md` for the step-by-step.
- **Orchestrator** → any container host with FFmpeg (its Dockerfile installs it).
  Point `CLIP_SERVER_URL` at the deployed Space and set `CLIP_SERVER_SECRET`.

See each service README for the full request/response contracts.
