# Brollio

Turn a narration audio file into a narrated **faceless video** by reviewing and
picking a visual for each spoken *beat*. This is the web frontend for the
faceless-video orchestrator.

Built with **Next.js (App Router) + TypeScript + Tailwind + shadcn-style UI +
lucide-react**.

## What it does

1. **Upload** a narration file (mp3 / wav / m4a) on `/`.
2. The orchestrator transcribes it and splits it into **beats**.
3. On `/edit/[id]` you review a **storyboard** — one suggested clip per beat —
   and swap any of them via the **clip picker** (Suggested / Search / Your
   library, or a caption editor for text cards).
4. Hit **Make video** to render, then **Download** the result.

Every beat is **pre-selected** with its top candidate, so you review and
override rather than starting from blank.

## Run locally (mock mode — no backend required)

```bash
npm install
npm run dev
# open http://localhost:3000
```

By default the app runs on **mock data** (`lib/mock.ts`), so the whole flow —
streaming beats, the picker, and a simulated render — works without the
orchestrator.

## Wire to the real orchestrator

Set these env vars (see `.env.example`) and the editor routes every call
through the built-in Next.js proxy in `app/api/*` (the bearer token stays
server-side):

```bash
NEXT_PUBLIC_USE_ORCHESTRATOR=1
ORCHESTRATOR_URL=http://localhost:8000     # FastAPI base URL
ORCHESTRATOR_TOKEN=dev-orch-secret         # matches API_AUTH_SECRET
```

### Orchestrator endpoints used

| Frontend call            | Proxy route                      | Orchestrator                       |
| ------------------------ | -------------------------------- | ---------------------------------- |
| `uploadAudio`            | `POST /api/videos`               | `POST /videos`                     |
| `getVideoJob` (poll)     | `GET /api/videos/{id}`           | `GET /videos/{id}`                 |
| storyboard beats         | `GET /api/videos/{id}/beats`     | `GET /videos/{id}/beats`           |
| `startRender`            | `POST /api/videos/{id}/render`   | `POST /videos/{id}/render`         |
| download                 | `GET /api/videos/{id}/download`  | `GET /videos/{id}/download`        |

Wire shapes are mapped in `lib/orchestrator.ts` against
`orchestrator/app/schemas.py`.

> **Note:** the orchestrator currently exposes only `broll` / `symbolic` visual
> types (plus a generated text fallback) and has no live per-beat search /
> user-upload endpoint. Those picker actions fall back to local behavior — see
> the `TODO`s in `lib/orchestrator.ts`.

## Docker

Standalone (frontend only, talks to an orchestrator on the host):

```bash
docker compose up --build        # from this folder → http://localhost:3000
```

Full stack (db + redis + clip-server + orchestrator + frontend):

```bash
docker compose up --build        # from the repo root
```

The image uses Next.js `output: "standalone"` for a minimal runtime.

## Project structure

```
app/
  page.tsx              upload screen
  edit/[id]/page.tsx    editor (storyboard + sidebar + picker + render)
  api/videos/...        server-side proxy to the orchestrator
components/             topbar, stepper, storyboard, beat row, sidebar, picker, render overlay, ui/*
lib/
  types.ts              Asset / Beat / VideoJob
  api.ts                mock-or-orchestrator API layer
  orchestrator.ts       real backend mapping
  mock.ts               sample storyboard
  store.ts              zustand editor store
```
