import type {
  AnimatedTextConfig,
  Aspect,
  Asset,
  AssetSource,
  Beat,
  BeatKind,
  ContentTheme,
  Quality,
  VideoJob,
  VisualType,
  Word,
} from "./types";
import type { RelWord } from "./animated-text";
import { relWordsToWire } from "./animated-text";
import type { VibeId } from "./vibes";
import { getPreviewAudioUrl } from "./preview-audio";

// Flip to true once the orchestrator exposes GET /videos/{id}/audio (so the
// synced preview survives a page refresh / shared link). Until then the preview
// relies on the in-memory blob from the current upload session.
const AUDIO_PROXY_ENABLED =
  process.env.NEXT_PUBLIC_AUDIO_PROXY === "1";

// ---------------------------------------------------------------------------
// Real orchestrator client.
//
// Calls the Next.js proxy routes in app/api/* (which inject the bearer token
// server-side — see ORCHESTRATOR_URL / ORCHESTRATOR_TOKEN env vars). This file
// is only the *mapping* between the orchestrator's wire shapes (see
// orchestrator/app/schemas.py) and the editor's types.ts.
//
// Activated by NEXT_PUBLIC_USE_ORCHESTRATOR=1 (see lib/api.ts).
// ---------------------------------------------------------------------------

// --- Orchestrator wire shapes (subset of orchestrator/app/schemas.py) -------
type OrchAssignment = {
  platform?: string | null;
  media_url?: string | null;
  preview_url?: string | null;
  kind?: string | null;
  score?: number | null;
  attribution?: string | null;
};
type OrchCandidate = OrchAssignment & { selected?: boolean };
type OrchWord = { t: string; s: number; e: number; f?: boolean };
type OrchBeat = {
  index: number;
  text: string;
  start_s: number;
  end_s: number;
  queries?: Record<string, unknown> | null;
  assignment?: OrchAssignment | null;
  candidates?: OrchCandidate[];
  words?: OrchWord[];
  kind?: string;
  duration_s?: number | null;
};
type OrchBeatsResponse = {
  beats: OrchBeat[];
  silence_spans?: [number, number][];
};
type OrchStatus =
  | "queued"
  | "transcribing"
  | "transcribed"
  | "llm"
  | "awaiting_clip"
  | "ready"
  | "render_queued"
  | "rendering"
  | "done"
  | "failed";
type OrchTheme = { mode?: string | null; vibe?: string | null } | null;

// --- Mappers ----------------------------------------------------------------

function mapSource(platform?: string | null): AssetSource {
  const p = (platform ?? "").toLowerCase();
  if (p.includes("animated")) return "animated";
  if (p.includes("wikimedia") || p.includes("wiki")) return "wikimedia";
  if (p.includes("user_video") || p.includes("upload") || p.includes("yours")) return "yours";
  return "pexels"; // pexels_photo / pixabay_photo / anything else
}

function candidateId(beatIndex: number, c: OrchCandidate, i: number): string {
  return `o-${beatIndex}-${i}-${(c.media_url ?? c.preview_url ?? "x").slice(-12)}`;
}

function mapCandidate(beat: OrchBeat, c: OrchCandidate, i: number): Asset {
  const kind = (c.kind ?? "").toLowerCase() === "video" ? "video" : "photo";
  const platform = (c.platform ?? "").toLowerCase();
  const isUserVideo = platform.includes("user_video") || platform.includes("upload");
  // A real image thumbnail only exists when preview_url is a distinct image
  // (stock photos, and stock videos whose preview is a still frame). The user's
  // own footage has preview_url === media_url (the video file itself), which is
  // NOT an image — using it as a poster shows a broken/black tile. In that case
  // leave thumbUrl empty so the picker renders the video's own first frame.
  const hasImageThumb = Boolean(c.preview_url) && c.preview_url !== c.media_url;
  return {
    id: candidateId(beat.index, c, i),
    thumbUrl: hasImageThumb
      ? (c.preview_url as string)
      : kind === "video"
        ? ""
        : c.media_url ?? "",
    source: mapSource(c.platform),
    kind,
    // Keep the streamable file for videos so the picker can play a preview.
    mediaUrl: kind === "video" ? c.media_url ?? undefined : undefined,
    sourceInS: kind === "video" && isUserVideo ? beat.start_s : undefined,
  };
}

function mapVisualType(beat: OrchBeat): VisualType {
  // The orchestrator only emits broll/symbolic + a "generated" text fallback.
  // A generated assignment (no real media) reads as a text card in the editor.
  if ((beat.assignment?.platform ?? "").toLowerCase() === "generated") return "text_card";
  const vt = (beat.queries?.visual_type as string | undefined)?.toLowerCase();
  if (vt === "symbolic") return "symbolic";
  return "broll";
}

function mapBeat(beat: OrchBeat): Beat {
  const beatKind: BeatKind = beat.kind === "insert" ? "insert" : "narration";
  const durationS =
    beatKind === "insert" && beat.duration_s != null ? Number(beat.duration_s) : undefined;
  const candidates = (beat.candidates ?? []).map((c, i) => mapCandidate(beat, c, i));
  const visualType = beatKind === "insert" ? "text_card" : mapVisualType(beat);
  const selectedIdx = (beat.candidates ?? []).findIndex((c) => c.selected);
  const chosenAssetId =
    selectedIdx >= 0
      ? candidates[selectedIdx]?.id ?? null
      : candidates[0]?.id ?? null;
  return {
    index: beat.index,
    from: beat.start_s,
    to: beatKind === "insert" && durationS != null ? beat.start_s + durationS : beat.end_s,
    text: beat.text,
    visualType,
    overlay: visualType === "text_card" ? beat.text.slice(0, 60) : undefined,
    loading: beatKind !== "insert" && candidates.length === 0 && visualType !== "text_card",
    included: true,
    chosenAssetId,
    candidates,
    words: (beat.words ?? []).map((w) => ({
      text: w.t,
      from: w.s,
      to: w.e,
      filler: Boolean(w.f),
    })),
    kind: beatKind,
    durationS,
  };
}

const RUNNING_STATUSES: OrchStatus[] = [
  "queued",
  "transcribing",
  "transcribed",
  "llm",
  "awaiting_clip",
  "render_queued",
  "rendering",
];

function mapTheme(t?: OrchTheme): ContentTheme {
  if (t && t.mode === "vibe" && t.vibe) {
    return { mode: "vibe", vibe: t.vibe as VibeId };
  }
  return { mode: "script" };
}

function mapStatus(s: OrchStatus): VideoJob["status"] {
  if (s === "done") return "done";
  if (s === "failed") return "failed";
  if (s === "ready") return "running"; // prepared; editor treats it as usable
  return RUNNING_STATUSES.includes(s) ? "running" : "queued";
}

// Rough numeric percent for the render overlay (orchestrator only ships a
// progress *string*). Tune as the backend reports finer progress.
const PROGRESS_PERCENT: Record<string, number> = {
  render_queued: 8,
  rendering: 55,
  done: 100,
};

// --- Calls (via the Next.js proxy, relative URLs) ---------------------------

async function jsonOrThrow(res: Response) {
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    // Prefer the orchestrator's human-readable {"detail": "..."} message (e.g.
    // tier-limit or insufficient-credit explanations) over a raw status string,
    // so callers can show the real reason to the user.
    let detail = "";
    try {
      const parsed = JSON.parse(text);
      if (parsed && typeof parsed.detail === "string") detail = parsed.detail;
    } catch {
      // Body wasn't JSON; fall back to the raw text below.
    }
    throw new Error(detail || text || `Request failed (${res.status}).`);
  }
  return res.json();
}

/**
 * The job either doesn't exist or isn't owned by the signed-in user. The
 * orchestrator returns 404 in both cases (it scopes every lookup to the caller's
 * user id, so another user's job is indistinguishable from a missing one — by
 * design, so ids can't be probed). Callers treat this as terminal, NOT a
 * transient/retryable error.
 */
export class JobNotFoundError extends Error {
  constructor(id: string) {
    super(`Video job ${id} not found.`);
    this.name = "JobNotFoundError";
  }
}

export async function orchUploadAudio(
  file: File,
  signal?: AbortSignal,
): Promise<{ videoJobId: string }> {
  const form = new FormData();
  form.append("audio", file);
  const data = await jsonOrThrow(
    await fetch("/api/videos", { method: "POST", body: form, signal }),
  );
  return { videoJobId: data.video_job_id };
}

export async function orchGetVideoJob(id: string): Promise<VideoJob> {
  const [statusRes, beatsRes] = await Promise.all([
    fetch(`/api/videos/${id}`),
    fetch(`/api/videos/${id}/beats`).then((r) => (r.ok ? r.json() : { beats: [] })),
  ]);
  // 404 (not found OR not owned) and 403 are terminal: don't retry, surface a
  // "not found" so the editor can bounce the user back to the home page.
  if (statusRes.status === 404 || statusRes.status === 403) {
    throw new JobNotFoundError(id);
  }
  const status = await jsonOrThrow(statusRes);
  const beatsData = beatsRes as OrchBeatsResponse;
  const beats: Beat[] = (beatsData.beats ?? []).map(mapBeat);
  const silenceSpans = beatsData.silence_spans ?? [];
  const s = status.status as OrchStatus;
  const durationSec = beats.length
    ? Math.round(Math.max(...beats.map((b) => b.to)))
    : undefined;
  return {
    id,
    status: mapStatus(s),
    stage: status.progress ?? s,
    percent: PROGRESS_PERCENT[status.progress ?? s] ?? (s === "done" ? 100 : 0),
    beats,
    aspect: "9:16",
    quality: "standard",
    captions: true,
    music: false,
    removeSilence: false,
    removeFillers: false,
    silenceSpans,
    theme: mapTheme(status.theme as OrchTheme),
    // The whole window before the clip search starts. Output choices can be
    // committed any time here (POST /prepare) — even while transcription is
    // still running — so the setup form is offered immediately on upload.
    awaitingSetup: s === "queued" || s === "transcribing" || s === "transcribed",
    error: s === "failed" ? (status.error ?? undefined) : undefined,
    resultUrl:
      status.status === "done" ? `/api/videos/${id}/download` : undefined,
    durationSec,
    // Prefer the in-memory blob from this upload session (instant, always
    // works). The /api/videos/{id}/audio proxy is only a usable fallback once
    // the orchestrator ships the matching endpoint — until then it 404s, so we
    // don't point the player at it (avoids an eager fetch + console noise).
    audioUrl: getPreviewAudioUrl(id) ?? (AUDIO_PROXY_ENABLED ? `/api/videos/${id}/audio` : undefined),
  };
}

export async function orchStartRender(
  id: string,
  opts?: {
    overrides?: Record<number, number>;
    excludedBeats?: number[];
    aspect?: Aspect;
    captions?: boolean;
    removeSilence?: boolean;
    removeFillers?: boolean;
  },
): Promise<void> {
  // Send the final output choices with the render call so swaps made on the
  // Pick Clips screen (clip, aspect, captions) are honored — the orchestrator
  // folds these into the job payload before encoding. See docs/IMPROVEMENTS.md.
  const body: {
    overrides?: Record<number, number>;
    excluded_beats?: number[];
    format?: string;
    subtitles?: boolean;
    remove_silence?: boolean;
    remove_fillers?: boolean;
  } = {};
  if (opts?.overrides && Object.keys(opts.overrides).length > 0) {
    body.overrides = opts.overrides;
  }
  if (opts?.excludedBeats !== undefined) {
    body.excluded_beats = opts.excludedBeats;
  }
  if (opts?.aspect) body.format = ASPECT_FORMAT[opts.aspect];
  if (opts?.captions !== undefined) body.subtitles = opts.captions;
  if (opts?.removeSilence !== undefined) body.remove_silence = opts.removeSilence;
  if (opts?.removeFillers !== undefined) body.remove_fillers = opts.removeFillers;

  const hasBody = Object.keys(body).length > 0;
  await jsonOrThrow(
    await fetch(`/api/videos/${id}/render`, {
      method: "POST",
      ...(hasBody
        ? {
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body),
          }
        : {}),
    }),
  );
}

// Editor aspect -> orchestrator format name (see orchestrator/app/formats.py).
// We send the generic orientation names, which formats.py aliases to concrete
// presets: landscape -> 1920x1080, portrait -> 1080x1920, square -> 1080x1080.
const ASPECT_FORMAT: Record<Aspect, string> = {
  "9:16": "portrait", // 1080x1920
  "16:9": "landscape", // 1920x1080
  "1:1": "square", // 1080x1080
};

const QUALITY_TIER: Record<Quality, string> = {
  standard: "hd",
  high: "max",
};

export async function orchPrepare(
  id: string,
  opts: { aspect: Aspect; quality: Quality; captions: boolean; theme?: ContentTheme },
): Promise<void> {
  const theme =
    opts.theme && opts.theme.mode === "vibe"
      ? { mode: "vibe", vibe: opts.theme.vibe }
      : { mode: "script" };
  const res = await fetch(`/api/videos/${id}/prepare`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      format: ASPECT_FORMAT[opts.aspect],
      quality: QUALITY_TIER[opts.quality],
      subtitles: opts.captions,
      theme,
    }),
  });
  if (res.status === 404 || res.status === 405) {
    // Production may still be running the legacy orchestrator, where clip search
    // starts automatically after transcription and /prepare doesn't exist yet.
    return;
  }
  if (res.status === 409) {
    // Already prepared / moved past the setup window (e.g. a page refresh raced
    // a prior prepare). The search is already underway — nothing more to do.
    return;
  }
  await jsonOrThrow(res);
}

// TODO: the orchestrator has no per-beat live search / user-upload endpoint yet.
// These fall back to the candidates already returned by /beats. Wire them up
// when the backend exposes a clip-search or asset-override route.
export async function orchSearchClips(
  _id: string,
  beatIndex: number,
  query: string,
): Promise<Asset[]> {
  const { makeSearchResults } = await import("./mock");
  return makeSearchResults(beatIndex, query);
}

/**
 * Insert a brand-new standalone animated text-card beat at ``position``. Existing
 * beats at/after it shift up; callers should re-fetch the job afterwards.
 */
export async function orchInsertAnimatedBeat(
  id: string,
  position: number,
  text: string,
  durationS: number,
  blob: Blob,
  config: AnimatedTextConfig,
  words: RelWord[],
): Promise<{ beatIndex: number; mediaUrl: string | null }> {
  const form = new FormData();
  const ext = blob.type.includes("mp4") ? "mp4" : "webm";
  form.append("clip", blob, `insert-${position}.${ext}`);
  form.append("position", String(position));
  form.append("text", text);
  form.append("duration_s", String(durationS));
  form.append("style", config.style);
  form.append("palette", config.palette);
  form.append("sound", config.sound);
  form.append("words", JSON.stringify(relWordsToWire(words)));
  const data = await jsonOrThrow(
    await fetch(`/api/videos/${id}/beats/insert`, {
      method: "POST",
      body: form,
    }),
  );
  return {
    beatIndex: Number(data.beat_index ?? position),
    mediaUrl: (data.media_url as string | null) ?? null,
  };
}

/**
 * Upload a browser-recorded animated text-card clip for one beat. The backend
 * stores it and registers it as a selected candidate; we return the candidate
 * index so the render override can re-select it, plus the stored media URL.
 */
export async function orchUploadAnimatedClip(
  id: string,
  beatIndex: number,
  blob: Blob,
  config: AnimatedTextConfig,
): Promise<{ candidateIndex: number; mediaUrl: string | null }> {
  const form = new FormData();
  const ext = blob.type.includes("mp4") ? "mp4" : "webm";
  form.append("clip", blob, `beat-${beatIndex}.${ext}`);
  form.append("style", config.style);
  form.append("palette", config.palette);
  form.append("sound", config.sound);
  const data = await jsonOrThrow(
    await fetch(`/api/videos/${id}/beats/${beatIndex}/clip`, {
      method: "POST",
      body: form,
    }),
  );
  return {
    candidateIndex: Number(data.candidate_index ?? 0),
    mediaUrl: (data.media_url as string | null) ?? null,
  };
}

/**
 * Correct a beat's transcript text (a typo fix). Only the caption text changes;
 * the backend re-syncs per-word timing when the word count is unchanged and
 * returns the updated words so the editor stays consistent.
 */
export async function orchUpdateBeatText(
  id: string,
  beatIndex: number,
  text: string,
): Promise<{ text: string; words: Word[] }> {
  const data = await jsonOrThrow(
    await fetch(`/api/videos/${id}/beats/${beatIndex}/text`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    }),
  );
  const words = (Array.isArray(data.words) ? data.words : []).map(
    (w: OrchWord) => ({
      text: w.t,
      from: w.s,
      to: w.e,
      filler: Boolean(w.f),
    }),
  );
  return { text: (data.text as string) ?? text, words };
}

export async function orchUploadOwnClip(
  _id: string,
  beatIndex: number,
  file: File,
): Promise<Asset> {
  const url = URL.createObjectURL(file);
  const kind = file.type.startsWith("video") ? "video" : "photo";
  return {
    id: `yours-${beatIndex}-${Date.now()}`,
    // User video has no still poster; keep the stream in mediaUrl so components
    // can mount it only when previewing instead of treating the blob as an image.
    thumbUrl: kind === "video" ? "" : url,
    source: "yours",
    kind,
    mediaUrl: kind === "video" ? url : undefined,
  };
}
