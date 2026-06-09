# Improvements & Future Work

Running log of known bottlenecks, technical debt, and recommended solutions.
Each entry captures the problem, why it matters, and concrete options so future
work can start from context instead of re-deriving it.

## Server-Side Video Rendering Bottleneck

**Status:** Accepted for now. Rendering stays server-side until queue wait times,
compute cost, or production load justify a deeper change.

### Problem

Final video rendering currently runs on the backend in
`orchestrator/app/renderer/ffmpeg.py`. It is the heaviest operation in the
system because each job may require:

- Downloading selected stock assets, with retries and deduping.
- Encoding every beat as an H.264 segment.
- Applying Ken Burns motion to photos.
- Trimming, looping, scaling, and cropping video clips.
- Rendering text-card beats.
- Burning Hormozi-style word-by-word captions into segments.
- Normalizing to constant 30 FPS.
- Concatenating segments and muxing narration audio.
- Uploading the final MP4 to cloud storage through `orchestrator/app/storage.py`.

This work is CPU-heavy and also depends on network I/O for external assets. As
usage grows, render throughput can become a bottleneck: users wait longer, queue
depth grows, and compute cost scales roughly with video length and job count.

### Why It Matters

- Render latency directly affects the final user experience.
- Backend compute cost grows with usage.
- Heavy render workers can contend with lighter orchestration/API work.
- A single server-side render path is reliable, but can become expensive if it is
  the only path for every platform and every job.

### Current Decision

Keep rendering server-side for now. The backend renderer already produces a
proper downloadable MP4, handles cloud upload, and gives consistent output across
all clients. The short-term focus should be making this server path easier to
scale before investing in client-side renderers.

## Persist Clip Overrides at Render Time (Implemented)

**Status:** Implemented (Option A — batch overrides into the render call).

### Problem
Changing a beat's clip in the editor only updated local UI state
(`chooseAsset` in `seemless/lib/store.ts`). The backend render rebuilds the
timeline from the stored `beat_assignments`, so a user's clip swap was shown in
the preview but **not** reflected in the rendered MP4.

### Why this approach
A per-click `PATCH` endpoint would be a featherweight DB write, but at scale the
concern is call *volume*, not per-call weight (a storyboard review can flip
through many candidates). The override only needs to be correct at render time,
so we batch the full selection map into the existing render call — one write,
no chatty autosave traffic, naturally idempotent.

### Implementation
- `POST /videos/{id}/render` accepts an optional body
  `{ "overrides": { "<beat_index>": <candidate_index> }, "format": "...",
  "subtitles": true }` (`RenderRequest`).
- `apply_candidate_overrides` (in `services/video_jobs.py`) repoints each
  assignment's media columns to the chosen candidate and moves the `selected`
  flag, committing once. Invalid/unknown entries are skipped; re-applying is a
  no-op.
- `format` / `subtitles` are folded into the stored job payload right before
  enqueueing, so changing the aspect ratio or caption toggle on the Pick Clips
  screen (after the clip search already ran) is honored by the final render.
- Frontend sends the full map for every beat whose pick is a server candidate
  (`renderOverrides` in `lib/store.ts`) plus the current aspect/captions
  (`startRender` -> `orchStartRender`), so re-renders always match the UI.

### Caveat — aspect changed after clip search
The orientation of the *stock media* is chosen at clip-search time from the
format set at `/prepare`. Changing `format` at render only changes the encoded
output dimensions (the renderer cover-scales and crops), not which clips were
fetched. Switching e.g. 9:16 -> 16:9 after the search can therefore crop
portrait-oriented clips. For best quality the aspect should still be chosen up
front; render-time change is a convenience, not a re-fetch.

### Known follow-up
User-uploaded clips (`Your library`) are not yet persisted to the backend, so
they can't be expressed as a `candidate_index` and are skipped. This needs the
asset-upload persistence path (an upload endpoint + storing the custom asset as
a candidate) before those selections can render.

## Recommended Strategy

### Phase 0: Scale the Existing Server Renderer

This is the lowest-risk improvement because it keeps the current rendering
behavior intact.

- Split render workers into a separately autoscaled pool.
- Scale render workers based on render queue depth and age.
- Run render workers on cheaper spot or preemptible machines where possible.
- Consider GPU-accelerated encoding with NVENC for high volume workloads.
- Tune `segment_concurrency`, FFmpeg `threads`, `preset`, and `crf` per machine
  type.
- Keep API/orchestrator workers separate from CPU-heavy render workers.
- Track render metrics: queue wait time, total render time, asset download time,
  encode time, upload time, failures, and retries.

### Phase 1: Define a Declarative Render Spec

Create a shared JSON render specification that describes the final timeline:

- Job id and output format.
- Aspect ratio, width, height, FPS, and quality.
- Narration audio reference.
- Ordered beat timeline.
- Asset URLs and selected clip metadata.
- Per-beat start/end times.
- Video trim/loop behavior.
- Photo animation parameters.
- Captions and styling.
- Logo/watermark placement.
- Per-word caption timings when available.

The current FFmpeg renderer should consume this spec first. This keeps behavior
unchanged while creating a stable contract for future web, iOS, Android, or
alternate cloud renderers.

### Phase 2: Persist Real Word-Level Caption Timings

The preview currently approximates word highlighting by distributing words across
each beat window. The backend subtitle renderer also approximates timing when
burning captions.

For accurate Hormozi-style captions, persist word-level timestamps from
transcription:

```json
{
  "word": "example",
  "start_s": 12.34,
  "end_s": 12.62
}
```

Store these timings in the render spec and use them in both preview and final
rendering. This avoids caption drift and gives every renderer the same timing
source.

### Phase 3: Add Client-Side Rendering Where It Makes Sense

Client-side rendering can reduce backend compute, but it should be platform
specific and always have a server fallback.

#### Native Mobile Apps

Native mobile is the strongest client-rendering candidate.

- iOS: use `AVMutableComposition`, `AVVideoComposition`, Core Animation layers,
  and `AVAssetExportSession`.
- Android: use Media3 Transformer or lower-level `MediaCodec`.
- Render on-device using hardware encoders.
- Support offline or background export where the platform allows it.
- Upload directly to cloud storage after export using a short-lived upload token.

#### Desktop Web

Desktop web can support optional client-side rendering for capable browsers.

- Prefer WebCodecs plus `OffscreenCanvas` and an MP4 muxer such as `mp4-muxer`
  or `mp4box.js`.
- Use feature detection and fall back to server rendering when unsupported.
- Avoid making this mandatory for all users.

#### Mobile Web

Do not rely on mobile-browser rendering as the default path.

Mobile browsers have tighter memory limits, inconsistent codec support, tab
suspension, battery constraints, and thermal throttling. Server rendering should
remain the default fallback for mobile web.

### Phase 4: Direct Client Uploads to Cloud Storage

If a client renders locally, it should not upload the MP4 through the backend.
The backend should issue a short-lived, scoped upload credential.

Recommended flow:

1. Client asks backend for an upload target for `job_id`.
2. Backend returns a short-lived presigned upload URL or B2 upload token scoped
   to a single object path.
3. Client uploads the MP4 directly to the bucket.
4. Client notifies backend that upload completed.
5. Backend verifies the object and records `result_url` on the job.

Important constraints:

- Never expose permanent B2 keys to clients.
- Scope upload permissions to one object path and a short expiration.
- Validate content type, expected size, and job ownership before finalizing.
- Keep server-side rendering as fallback when client upload or client export
  fails.

## Recommended Long-Term Architecture

Use a hybrid renderer model:

- Server FFmpeg renderer remains the source of truth and universal fallback.
- Native mobile apps can render on-device for lower backend cost.
- Desktop web can render locally only when the browser is capable.
- Mobile web uses server rendering by default.
- All renderers consume the same render spec.
- Final MP4s are uploaded to cloud storage and recorded on the job regardless of
  where rendering happened.

This approach avoids betting the product on fragile browser rendering while
still creating a path to reduce backend render cost as usage grows.

