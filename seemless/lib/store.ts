import { create } from "zustand";
import type { Asset, Aspect, Beat, Quality, VideoJob } from "./types";
import { getVideoJob, prepareJob, startRender, type RenderSettings } from "./api";
import { JobNotFoundError } from "./orchestrator";
import { forgetPreviewAudio } from "./preview-audio";

type EditorState = {
  job: VideoJob | null;
  loading: boolean;
  preparing: boolean;
  // True once a load/poll resolves the job as missing or not owned by the
  // signed-in user. The editor uses this to redirect back to the home page.
  notFound: boolean;
  // actions
  load: (id: string) => Promise<void>;
  stopPolling: () => void;
  prepare: () => Promise<void>;
  render: () => Promise<void>;
  chooseAsset: (beatIndex: number, assetId: string) => void;
  addCandidate: (beatIndex: number, asset: Asset, select?: boolean) => void;
  setOverlay: (beatIndex: number, overlay: string) => void;
  updateSettings: (
    patch: Partial<Pick<VideoJob, "aspect" | "quality" | "captions" | "music" | "theme">>,
  ) => void;
};

function releaseLocalAssetUrls(job: VideoJob | null): void {
  if (!job) return;
  const seen = new Set<string>();
  for (const beat of job.beats) {
    for (const asset of beat.candidates) {
      if (asset.source !== "yours") continue;
      for (const url of [asset.thumbUrl, asset.mediaUrl]) {
        if (url?.startsWith("blob:") && !seen.has(url)) {
          seen.add(url);
          URL.revokeObjectURL(url);
        }
      }
    }
  }
}

function releaseJobBlobs(job: VideoJob | null): void {
  if (!job) return;
  releaseLocalAssetUrls(job);
  forgetPreviewAudio(job.id);
}

function mutateBeat(job: VideoJob, index: number, fn: (b: Beat) => Beat): VideoJob {
  return { ...job, beats: job.beats.map((b) => (b.index === index ? fn(b) : b)) };
}

/**
 * Optimistic job shown the instant the editor mounts, BEFORE the first poll.
 *
 * The setup choices (aspect/quality/captions/theme) don't depend on the
 * transcript, so we must never hide them behind a successful first poll: the
 * orchestrator runs on a cold/CPU-bound host and a slow upload + transcription
 * can make early polls 502 / time out. Seeding here means the setup card is
 * always reachable; the poll loop streams the real status + beats in over it.
 */
function seedJob(id: string): VideoJob {
  return {
    id,
    status: "queued",
    stage: "Uploading & transcribing",
    percent: 0,
    beats: [],
    aspect: "9:16",
    quality: "standard",
    captions: true,
    music: false,
    theme: { mode: "script" },
    awaitingSetup: true,
  };
}

// --- Polling: stream beats/clips in as the pipeline progresses --------------

const POLL_INTERVAL_MS = 2000;
// On repeated fetch errors we back off exponentially (instead of hammering the
// backend every 2s) and, after enough consecutive failures, give up with a
// terminal "unreachable" state rather than polling forever.
const POLL_BACKOFF_MAX_MS = 30_000;
const MAX_POLL_ERRORS = 8;
// A non-terminal job that sits in the same phase this long is flagged "slow"
// (a soft hint, not a failure — the server may still finish it).
const SLOW_AFTER_MS = 90_000;
// Absolute backstop: a non-render job that never settles is failed client-side.
// Set well above the orchestrator's summed stage deadlines so a legitimately
// slow job is never killed; rendering is exempt (it can run for many minutes and
// the server owns its own deadline).
const GIVE_UP_AFTER_MS = 45 * 60_000;

// Module-scoped poll state (the store is a singleton; only one editor mounts).
let pollTimer: ReturnType<typeof setTimeout> | null = null;
let activeId: string | null = null;
let pollErrors = 0;
let phaseStartedAt = 0;
let lastStage: string | null = null;

/** Raw orchestrator progress strings that mean "render in flight". */
function isRenderingStage(job: VideoJob): boolean {
  return job.stage === "render_queued" || job.stage === "rendering";
}

/** True once nothing more will stream in: terminal status, or every beat has resolved. */
function isSettled(job: VideoJob): boolean {
  if (job.status === "done" || job.status === "failed") return true;
  // A render in progress must keep polling so the page advances to "done"
  // (this is also what makes a mid-render page refresh recover the progress).
  if (isRenderingStage(job)) return false;
  return job.beats.length > 0 && job.beats.every((b) => !b.loading);
}

/**
 * Merge a freshly polled job into the current one, PRESERVING the user's work:
 * a beat that already resolved (and may carry an override or an uploaded clip)
 * is kept as-is; only still-loading beats take the incoming data. Local-only
 * settings (aspect/captions/music) and the display filename are also kept.
 */
function mergeJob(prev: VideoJob | null, incoming: VideoJob): VideoJob {
  if (!prev) return incoming;
  const prevById = new Map(prev.beats.map((b) => [b.index, b]));
  const beats = incoming.beats.map((inc) => {
    const existing = prevById.get(inc.index);
    return existing && !existing.loading ? existing : inc;
  });
  return {
    ...incoming,
    beats,
    aspect: prev.aspect,
    quality: prev.quality,
    captions: prev.captions,
    music: prev.music,
    theme: prev.theme ?? incoming.theme,
    // Once the user commits output choices we own these flags locally so a
    // mid-flight poll (server still at "transcribed") can't bounce us back.
    prepared: prev.prepared || incoming.prepared,
    awaitingSetup: prev.prepared ? false : incoming.awaitingSetup,
    fileName: prev.fileName ?? incoming.fileName,
    durationSec: incoming.durationSec ?? prev.durationSec,
    audioUrl: prev.audioUrl ?? incoming.audioUrl,
  };
}

export const useEditorStore = create<EditorState>((set, get) => {
  // Shared poll loop: pulls the job snapshot and keeps polling until the job is
  // settled (terminal status, all beats resolved, and not mid-render). Used by
  // both load() and render() — and, because render progress isn't settled, a
  // page refresh during a render resumes tracking it automatically.
  const beginPolling = (id: string) => {
    if (pollTimer) clearTimeout(pollTimer);
    pollErrors = 0;
    phaseStartedAt = Date.now();
    lastStage = null;
    const schedule = (ms: number) => {
      pollTimer = setTimeout(poll, ms);
    };
    const failJob = (stage: string, error: string) => {
      set((state) =>
        state.job
          ? { job: { ...state.job, status: "failed", stage, error, slow: false }, loading: false }
          : {},
      );
    };
    const poll = async () => {
      if (activeId !== id) return;
      let incoming: VideoJob;
      try {
        incoming = await getVideoJob(id);
      } catch (e) {
        if (activeId !== id) return;
        // Missing or not-owned job: terminal. Stop polling and flag notFound so
        // the editor can show "project not found" and return to the home page.
        if (e instanceof JobNotFoundError) {
          activeId = null;
          if (pollTimer) {
            clearTimeout(pollTimer);
            pollTimer = null;
          }
          set({ notFound: true, loading: false });
          return;
        }
        pollErrors += 1;
        if (pollErrors >= MAX_POLL_ERRORS) {
          // Give up rather than poll forever: surface a retryable terminal state.
          failJob(
            "unreachable",
            "We couldn't reach the server. Check your connection and try again.",
          );
          return;
        }
        // Exponential backoff with jitter so a struggling backend isn't hammered.
        const delay = Math.min(POLL_BACKOFF_MAX_MS, POLL_INTERVAL_MS * 2 ** (pollErrors - 1));
        schedule(delay + Math.random() * 500);
        return;
      }
      if (activeId !== id) return;
      pollErrors = 0;
      // Reset the "slow" baseline whenever the pipeline advances to a new phase.
      if (incoming.stage !== lastStage) {
        lastStage = incoming.stage;
        phaseStartedAt = Date.now();
      }
      const inPhaseMs = Date.now() - phaseStartedAt;
      set((state) => {
        const merged = mergeJob(state.job, incoming);
        const slow = !isSettled(merged) && inPhaseMs > SLOW_AFTER_MS;
        return { job: { ...merged, slow }, loading: false };
      });
      const current = get().job;
      if (current && !isSettled(current)) {
        if (inPhaseMs > GIVE_UP_AFTER_MS && !isRenderingStage(current)) {
          failJob(
            "timeout",
            "This is taking much longer than expected. Please try again.",
          );
          return;
        }
        schedule(POLL_INTERVAL_MS);
      }
    };
    return poll();
  };

  return {
    job: null,
    loading: true,
    preparing: false,
    notFound: false,

    load: async (id) => {
      activeId = id;
      // Render the setup screen immediately instead of blocking on the first
      // poll. If a job for this id is already in memory (re-mount), keep it.
      set((state) => ({
        job: state.job && state.job.id === id ? state.job : seedJob(id),
        loading: false,
        notFound: false,
      }));
      await beginPolling(id);
    },

    stopPolling: () => {
      activeId = null;
      pollErrors = 0;
      lastStage = null;
      if (pollTimer) {
        clearTimeout(pollTimer);
        pollTimer = null;
      }
      const { job } = get();
      releaseJobBlobs(job);
      set({ job: null, loading: true, notFound: false });
    },

    prepare: async () => {
      const { job } = get();
      if (!job || job.prepared) return;
      set({ preparing: true });
      // Optimistically leave the setup phase. The poll loop keeps running and
      // streams clips in once the search starts server-side. If transcription is
      // still going, the search auto-starts the moment beats are ready.
      const hasBeats = job.beats.length > 0;
      set({
        job: {
          ...job,
          prepared: true,
          awaitingSetup: false,
          stage: hasBeats ? "Finding clips" : "Finishing transcription",
        },
      });
      try {
        await prepareJob(job.id, {
          aspect: job.aspect,
          quality: job.quality,
          captions: job.captions,
          theme: job.theme,
        });
      } finally {
        set({ preparing: false });
      }
    },

    render: async () => {
      const { job } = get();
      if (!job) return;
      // Optimistically flip into the render phase so the UI swaps to the render
      // panel immediately (and a re-render clears a previous result).
      activeId = job.id;
      set({
        job: {
          ...job,
          status: "running",
          stage: "render_queued",
          percent: 8,
          resultUrl: undefined,
        },
      });
      const settings: RenderSettings = {
        aspect: job.aspect,
        captions: job.captions,
        music: job.music,
      };
      try {
        await startRender(job.id, settings, renderOverrides(job));
      } catch (e) {
        // Surface the orchestrator's reason (e.g. "Video is 95s but the Free
        // tier allows at most 60s" or an insufficient-credits message) instead
        // of a generic failure, so the user knows how to fix it.
        const error =
          e instanceof Error && e.message
            ? e.message
            : "We couldn't start the render. Please try again.";
        set((state) =>
          state.job
            ? {
                job: {
                  ...state.job,
                  status: "failed",
                  stage: "render_failed",
                  error,
                },
              }
            : {},
        );
        return;
      }
      // Track render -> done via the shared poll loop.
      await beginPolling(job.id);
    },

    chooseAsset: (beatIndex, assetId) => {
      // TODO(orchestrator): persist the override (optimistic update for now).
      const { job } = get();
      if (!job) return;
      set({ job: mutateBeat(job, beatIndex, (b) => ({ ...b, chosenAssetId: assetId })) });
    },

    addCandidate: (beatIndex, asset, select = true) => {
      const { job } = get();
      if (!job) return;
      set({
        job: mutateBeat(job, beatIndex, (b) => ({
          ...b,
          candidates: [asset, ...b.candidates.filter((c) => c.id !== asset.id)],
          chosenAssetId: select ? asset.id : b.chosenAssetId,
        })),
      });
    },

    setOverlay: (beatIndex, overlay) => {
      const { job } = get();
      if (!job) return;
      set({ job: mutateBeat(job, beatIndex, (b) => ({ ...b, overlay })) });
    },

    updateSettings: (patch) => {
      // TODO(orchestrator): updateSettings -> render request body (aspect=format,
      // captions=subtitles). Local optimistic update for now.
      const { job } = get();
      if (!job) return;
      set({ job: { ...job, ...patch } });
    },
  };
});

// --- Derived selectors ------------------------------------------------------

export function beatNeedsChoice(b: Beat): boolean {
  if (b.visualType === "text_card") return !(b.overlay && b.overlay.trim().length > 0);
  return !b.chosenAssetId;
}

export function chosenCount(job: VideoJob | null): { chosen: number; total: number } {
  if (!job) return { chosen: 0, total: 0 };
  const total = job.beats.length;
  const chosen = job.beats.filter((b) => !beatNeedsChoice(b) && !b.loading).length;
  return { chosen, total };
}

export function findChosenAsset(beat: Beat): Asset | null {
  if (!beat.chosenAssetId) return null;
  return beat.candidates.find((c) => c.id === beat.chosenAssetId) ?? null;
}

/**
 * Build the render override map (beat index -> chosen backend candidate index)
 * sent with POST /render so the encoded video matches the editor's picks.
 *
 * We send the FULL map (including index 0) for every beat whose selection is a
 * server candidate, so a re-render always reflects the current UI even if a
 * prior render had swapped that beat. Beats whose pick is NOT a server
 * candidate (e.g. a user-uploaded clip, id `yours-…`) are skipped — those need
 * the not-yet-built asset-upload persistence path. Backend candidate ids look
 * like `o-{beatIndex}-{candidateIndex}-{suffix}` (see lib/orchestrator.ts).
 */
export function renderOverrides(job: VideoJob | null): Record<number, number> {
  const out: Record<number, number> = {};
  if (!job) return out;
  for (const beat of job.beats) {
    if (!beat.chosenAssetId) continue;
    const m = /^o-\d+-(\d+)-/.exec(beat.chosenAssetId);
    if (!m) continue;
    out[beat.index] = Number(m[1]);
  }
  return out;
}

export type JobPhase =
  | "setup"
  | "preparing"
  | "searching"
  | "ready"
  | "rendering"
  | "done"
  | "failed";

/**
 * Where the job is in the pipeline, for the storyboard + stepper.
 *
 * "setup" is offered immediately on upload — the output choices don't depend on
 * the transcript, so the user fills them while transcription runs in the
 * background. Transcription progress (and any beats that have arrived) is shown
 * alongside the setup form.
 */
export function jobPhase(job: VideoJob | null): JobPhase {
  if (!job) return "setup";
  if (job.status === "failed") return "failed";
  // Terminal: the MP4 is rendered and ready to download.
  if (job.status === "done") return "done";
  // Render in flight (also how a mid-render page refresh recovers the state).
  if (job.stage === "render_queued" || job.stage === "rendering") return "rendering";
  // The user hasn't committed output settings yet -> show setup right away,
  // even if transcription is still in flight (awaitingSetup spans the whole
  // pre-clip-search window).
  if (job.awaitingSetup && !job.prepared) return "setup";
  // Settings committed. Beats haven't streamed in yet (transcription/LLM still
  // running) -> waiting; otherwise the clip search is streaming or done.
  if (job.beats.length === 0) return "preparing";
  if (job.beats.some((b) => b.loading)) return "searching";
  return "ready";
}

/** Active stepper key derived from the pipeline phase. */
export function stepKeyForPhase(phase: JobPhase): string {
  if (phase === "setup") return "setup";
  if (phase === "preparing") return "beats";
  if (phase === "rendering" || phase === "done") return "render";
  return "pick";
}

export const ASPECTS: Aspect[] = ["9:16", "16:9", "1:1"];

export const QUALITIES: { value: Quality; label: string; hint: string }[] = [
  { value: "standard", label: "Standard", hint: "HD · faster" },
  { value: "high", label: "High", hint: "Max res · slower" },
];
