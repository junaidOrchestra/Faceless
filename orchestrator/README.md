---
title: Faceless Video Orchestrator
emoji: 🎬
colorFrom: indigo
colorTo: purple
sdk: docker
app_port: 8000
pinned: false
---

# Orchestrator — audio → faceless video

Beat/video-aware service: transcribe narration, LLM keywords per beat, batch-call the
CLIP server, build a timeline, render with FFmpeg.

## Deploy to Hugging Face Spaces (Docker)

This image bundles **Redis inside the container** (a Space only exposes one
service on one port), so the worker pool's job queue just works — no sibling
service needed. `entrypoint.sh` launches `redis-server` in the background, then
`uvicorn` in the foreground.

1. **Create a Space**: New Space → SDK **Docker** → *Blank*. The Space repo root
   must be the contents of this `orchestrator/` folder (it needs `Dockerfile`,
   `entrypoint.sh`, `app/`, `requirements.txt`, `migrations.sql`, and this
   `README.md` with the YAML metadata above).

2. **Run the DB migration once** against your Postgres (Neon):
   `psql "$DATABASE_URL" -f migrations.sql`.

3. **Set Space secrets** (Settings → *Variables and secrets*). At minimum:

   | Secret | Notes |
   | ------ | ----- |
   | `DATABASE_URL` | `postgresql+psycopg://user:pw@host/db` (Neon) |
   | `API_AUTH_SECRET` | bearer token clients must send |
   | `CLIP_SERVER_URL` | your clip-server Space URL |
   | `CLIP_SERVER_SECRET` | clip-server bearer token |
   | `CEREBRAS_API_KEY` | (or the relevant `LLM_PROVIDER` key) |
   | `STORAGE_LOCAL` | **set to `false`** — see storage note |
   | `B2_KEY_ID` / `B2_APPLICATION_KEY` / `B2_BUCKET_NAME` | required when `STORAGE_LOCAL=false` |
   | `WORKER_CONCURRENCY` | `1`–`2` on the free CPU tier (2 vCPU + ffmpeg) |

4. **Push** the folder to the Space's git remote; HF builds the Dockerfile and
   serves it on `app_port` (8000).

> **Storage on Spaces is ephemeral.** With `STORAGE_LOCAL=true` the rendered mp4
> is written to the container's `/tmp` and is unreachable after the request /
> restart. For a real deployment set `STORAGE_LOCAL=false` and configure
> Backblaze B2 so `result_url` is a durable cloud URL.

> **Restarts are safe.** On boot the worker resets orphaned `running` jobs to
> `queued` in Postgres and rebuilds the in-memory Redis queue from the database,
> so a Space sleep/restart doesn't lose jobs.

> **External Redis (optional).** To use a managed Redis (e.g. Upstash) instead of
> the bundled one, set the `REDIS_URL` secret; it overrides the in-container
> default.

## Endpoints

Bearer auth on all routes except `GET /health`.

### `POST /videos` → `202 {video_job_id}`

Multipart form:

- `audio` — narration file (mp3/wav/m4a), **or**
- `audio_url` — URL to download audio
- `sources` — optional JSON list forwarded to CLIP server
- `pexels_key` — optional, forwarded in memory only

### `GET /videos/{video_job_id}`

```json
{
  "video_job_id": "uuid",
  "status": "queued|running|done|failed",
  "progress": "transcribing|llm_vocabulary|clip_search|rendering",
  "result_url": "file:///tmp/faceless-results/{id}.mp4",
  "error": null
}
```

### `GET /health`

No auth.

## Pipeline (background)

1. Transcribe (faster-whisper) → beats with timestamps
2. LLM vocabulary — **one** call
3. LLM beat_queries — **one** batched call
4. POST CLIP `/jobs` → poll until `status=done`
5. Map `ref` → beat, pick top asset, fallback on failure
6. FFmpeg render (Ken Burns / trim / text cards) → `result_url`

## Swappable interfaces

| ABC          | Implementations        |
| ------------ | ---------------------- |
| LLMProvider  | gemini, cerebras, local, stub |
| Transcriber  | faster-whisper, stub   |
| ClipClient   | HTTP, stub             |
| Renderer     | FFmpeg, stub           |

## Environment

See `.env.example`. Required: `DATABASE_URL`, `API_AUTH_SECRET`, `CLIP_SERVER_SECRET`.

Set `LLM_PROVIDER=stub` and `USE_STUB_CLIP=1` / `USE_STUB_RENDERER=1` for tests.

## Run

```bash
pip install -r requirements.txt
export DATABASE_URL=postgresql+psycopg://faceless:faceless@localhost:5432/orchestrator
export API_AUTH_SECRET=dev-orch-secret
export CLIP_SERVER_URL=http://localhost:7860
export CLIP_SERVER_SECRET=dev-clip-secret
export LLM_PROVIDER=stub
psql "$DATABASE_URL" -f migrations.sql
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## Inspect beats locally without Docker

Use this when you only want to see how an audio file is chunked into visual beats.
It runs only `faster-whisper` plus the rule-based segmentation pass: no database,
no FastAPI server, no LLM, no CLIP server, no rendering.

Use Python 3.11 or 3.12. Python 3.14 is not recommended because compiled ML
packages may not have wheels yet.

```powershell
cd C:\Code\AI\faceless_video\orchestrator
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements-beats.txt

python inspect_beats.py C:\Code\AI\audios\narration.mp3 --model base --min 2.5 --target 3.5 --max 5 --pause 0.35
```

First run downloads the Whisper model. Later runs reuse the local model cache.

## Optional local GGUF LLM

`llama-cpp-python` is intentionally **not** in `requirements.txt` because it often
requires native compilation and can break normal installs/builds. Install it only
when you actually run with `LLM_PROVIDER=local`:

```bash
pip install -r requirements-local-llm.txt
```

## Tests

```bash
export USE_STUB_CLIP=1 USE_STUB_RENDERER=1
pytest
```
