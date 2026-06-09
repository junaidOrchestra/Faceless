# Faceless Video — Testing Suite

Give it YouTube links, get finished videos. The suite drives the orchestrator
API end-to-end with **no human in the loop**: it fetches each video's audio,
submits it, fills in the settings (content vs. vibe, aspect, quality, subtitles),
auto-advances every step using the **default selected clip** for each beat, times
each step, and hands you a download button (or auto-downloads) at the end.

```
YouTube link ──► fetch audio ──► submit ──► transcribe ──► prepare ──►
clip search ──► render ──► download  (every step timed, fully automatic)
```

## Run it

```bash
cd "testing suite"
docker compose up --build
```

Then open **http://localhost:8090**.

- Backend API (for debugging) is on **http://localhost:8899** (e.g. `GET /api/health`).
- Finished MP4s are also written to **`./output/`** on the host.

> The first run builds two images (the backend installs `ffmpeg` + `yt-dlp`),
> so give it a minute.

## How to use the UI

1. Paste one or more YouTube URLs (use **+ Add link** for more rows).
2. Per row, pick:
   - **Content** — *Match content (script)* or one of the **vibes** (space, ocean, …).
   - **Aspect** — 16:9 / 9:16 / 1:1.
   - **Quality** — SD / HD / Max.
   - **Subs** — burn-in subtitles (on by default).
   - The *Defaults* box pre-fills new rows.
3. Optionally tick **Auto-download finished videos**.
4. Hit **Run pipeline**. Each card shows a live, timed step-by-step timeline and a
   **Download video** button when done.

## Configuration

Settings come from `.env` (see `.env.example`). All have working defaults, so it
runs as-is against the deployed orchestrator.

| Variable | Default | Notes |
| --- | --- | --- |
| `ORCHESTRATOR_URL` | deployed HF Space | Where the pipeline lives. |
| `ORCHESTRATOR_TOKEN` | `orchestra-token-784631` | Bearer token (must match the orchestrator). |
| `SOURCES` | `["pexels_video"]` | Stock sources forwarded to the clip search. |
| `PEXELS_KEY` | (repo key) | Forwarded to the clip server. |
| `AUDIO_BITRATE_KBPS` | `64` | Mono MP3 bitrate; keeps uploads under the 50 MB limit. |
| `MAX_CONCURRENCY` | `2` | Videos processed in parallel. |
| `STAGE_TIMEOUT_S` | `2400` | Max wait per polling stage (clip search / render). |
| `POT_PROVIDER_URL` | `http://pot-provider:4416` | bgutil PO-token provider sidecar (auto-bypasses YouTube gating). |
| `YOUTUBE_PLAYER_CLIENTS` | (empty) | yt-dlp clients; empty = its defaults (best with the POT provider). |
| `YOUTUBE_AUDIO_FORMAT` | http (non-HLS) selector | Skips HLS (avoids empty-fragment downloads). |
| `YOUTUBE_COOKIES_FILE` | — | cookies.txt path — the reliable fix for gated videos (see below). |

## Troubleshooting YouTube downloads

YouTube gates its good (non-HLS) formats behind a **PO token**. The suite runs a
**`pot-provider`** sidecar (`brainicism/bgutil-ytdlp-pot-provider`) and a yt-dlp
plugin that mints those tokens automatically, so most public videos download
without any manual setup. It also skips HLS (whose fragments can download empty:
*"The downloaded file is empty"*).

If a specific video still fails (age-restricted / region-locked / heavy bot
checks), or you see repeated *HTTP 429 Too Many Requests*, add cookies — now a
**drop-in folder**, no config edits:

1. In a logged-in browser, export cookies for `youtube.com` to a Netscape
   `cookies.txt` (e.g. the "Get cookies.txt" browser extension).
2. Save it as `cookies.txt` in the **`cookies/`** folder next to
   `docker-compose.yml` (auto-detected; any `*.txt` works).
3. `docker compose restart backend`.

> HTTP 429 means YouTube is rate-limiting this server's IP (often after many
> quick requests). The backend already retries transient 429s with backoff
> (`YOUTUBE_FETCH_RETRIES` / `YOUTUBE_RETRY_BACKOFF_S`), but a persistently
> flagged IP needs cookies.

### Pointing at a local orchestrator

To test against the orchestrator from the repo root `docker-compose.yml`
(running on `localhost:8000`), set in `.env`:

```env
ORCHESTRATOR_URL=http://host.docker.internal:8000
ORCHESTRATOR_TOKEN=dev-orch-secret
```

## Architecture

- **`backend/`** — FastAPI. `yt-dlp` pulls audio; `orchestrator_client.py` calls
  `POST /videos` → `POST /prepare` → `POST /render` → `GET /download`;
  `pipeline.py` runs each job and records per-step timings; state is kept in
  memory and surfaced via `/api/batches/{id}`.
- **`frontend/`** — static HTML/CSS/JS served by nginx, which also reverse-proxies
  `/api` to the backend (so the browser hits a single origin, no CORS).

## API (backend)

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/health` | Liveness + which orchestrator. |
| `GET` | `/api/config` | Vibe / format / quality options for the UI. |
| `POST` | `/api/batches` | Start a batch: `{ "videos": [{ "url", "theme_mode", "vibe", "video_format", "quality", "subtitles" }] }`. |
| `GET` | `/api/batches/{id}` | Batch progress with per-job step timings. |
| `GET` | `/api/jobs/{id}` | Single job detail. |
| `GET` | `/api/jobs/{id}/video` | Download the finished MP4. |
