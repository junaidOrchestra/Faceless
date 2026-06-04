# CLIP Server — keywords → ranked assets

Beat-**agnostic** media finder: given a batch of keywords it searches stock
sources, embeds previews with CLIP, ranks by cosine similarity, and returns assets.
It knows nothing about audio, beats, videos, or rendering.

## Endpoints

All routes except `GET /health` require `Authorization: Bearer <API_AUTH_SECRET>`.

### `POST /jobs` → `202 {job_id}`

```json
{
  "job_id": "client-uuid",
  "items": [{"ref": "0", "keyword": "ocean waves", "sources": ["stub"]}],
  "credentials": {"pexels": "OPTIONAL_KEY"},
  "options": {"orientation": "landscape", "per_page": 15, "min_score": 0.2}
}
```

- **Idempotent** on `job_id` — resubmitting returns the existing job.
- Credentials are used in memory only; never logged or stored.

### `GET /jobs/{job_id}`

```json
{
  "job_id": "client-uuid",
  "status": "queued|running|done|failed",
  "items": [
    {
      "ref": "0",
      "assets": [
        {
          "platform": "stub",
          "kind": "photo",
          "media_url": "https://...",
          "preview_url": "https://...",
          "attribution_name": "...",
          "attribution_url": "...",
          "license": "CC0",
          "duration": null,
          "score": 0.87
        }
      ],
      "error": null
    }
  ],
  "error": null
}
```

When `status` is `done`, results are included. After a successful fetch the job is
**pruned** (with log line `job {id} processed: [keywords]`). `404` only for unknown ids.

### `POST /text-embed`

```json
{"texts": ["ocean waves"]}
→ {"embeddings": [[...]], "dim": 512}
```

### `GET /health`

`{"status": "ok", "version": "0.1.0"}` — no auth.

## Stock sources

| Name           | Key?   | Kind   |
| -------------- | ------ | ------ |
| `pexels_photo` | Pexels | photo  |
| `pexels_video` | Pexels | video  |
| `wikimedia`    | none   | photo  |
| `stub`         | none   | test   |

Register a new source: one file + `@register_source` + config.

## Cache-first vector search

When `ENABLE_CACHE_FIRST=true` (default), each item first runs an HNSW similarity
search over the `assets` table (CLIP cosine) scoped to the requested providers. If
enough matches clear `min_score`, the item is answered **from cache with no source
calls** — lower latency and fewer Pexels/Wikimedia requests. Otherwise the sources
are queried to backfill, and fresh results are merged (de-duplicated on
`(platform, external_id)`) with any cache hits. Requires the `idx_assets_embedding`
HNSW index from `migrations.sql` (pgvector >= 0.5.0).

## Environment

See `.env.example`. Required: `DATABASE_URL`, `API_AUTH_SECRET`.

## Run locally

```bash
pip install -r requirements.txt
export DATABASE_URL=postgresql+psycopg://faceless:faceless@localhost:5432/clip
export API_AUTH_SECRET=dev-clip-secret
export ENABLED_SOURCES='["stub"]'
psql "$DATABASE_URL" -f migrations.sql  # or use docker-compose from repo root
uvicorn app.main:app --host 0.0.0.0 --port 7860
```

## Tests

```bash
export DATABASE_URL=postgresql+psycopg://faceless:faceless@localhost:5432/clip
export API_AUTH_SECRET=test-secret
export ENABLED_SOURCES='["stub"]'
pytest
```

## Deploy — Hugging Face Spaces (Docker SDK)

1. Create a **Docker** Space (16 GB RAM, CPU).
2. Push this `clip-server/` directory (or monorepo subpath) with the provided `Dockerfile`.
3. Set Space secrets / env: `DATABASE_URL` (external Postgres with pgvector),
   `API_AUTH_SECRET`, `ENABLED_SOURCES` (e.g. `["pexels_photo","pexels_video","wikimedia"]`).
4. Expose port **7860** (default in Dockerfile).
5. Health check hits `/health`.
