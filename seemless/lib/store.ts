import { create } from "zustand";
import type { AnimatedTextConfig, Asset, Aspect, Beat, Quality, VideoJob } from "./types";
import type { RelWord } from "./animated-text";
import {
  getVideoJob,
  insertAnimatedBeat as insertAnimatedBeatApi,
  prepareJob,
  searchAllClips,
  startRender,
  updateBeatText as updateBeatTextApi,
  uploadAnimatedClip as uploadAnimatedClipApi,
  type RenderSettings,
} from "./api";
import { ASPECT_DIMS } from "./animated-text";
import { JobNotFoundError } from "./orchestrator";
import { forgetPreviewAudio } from "./preview-audio";
import { resyncWords } from "./utils";

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
  /** Opt-in stock b-roll search for a user-video upload (all beats). */
  findBrollForAll: () => Promise<void>;
  render: () => Promise<void>;
  chooseAsset: (beatIndex: number, assetId: string) => void;
  toggleBeat: (beatIndex: number) => void;
  setAllBeatsIncluded: (included: boolean) => void;
  addCandidate: (beatIndex: number, asset: Asset, select?: boolean) => void;
  insertAnimatedBeat: (
    position: number,
    text: string,
    durationS: number,
    blob: Blob,
    config: AnimatedTextConfig,
    words: RelWord[],
  ) => Promise<void>;
  setOverlay: (beatIndex: number, overlay: string) => void;
  editBeatText: (beatIndex: number, text: string) => Promise<void>;
  /** Re-record the beat's animated text card with its current text/config. */
  rerecordAnimatedCard: (beatIndex: number) => Promise<void>;
  updateSettings: (
    patch: Partial<
      Pick<
        VideoJob,
        | "aspect"
        | "quality"
        | "captions"
        | "music"
        | "theme"
        | "removeSilence"
        | "removeFillers"
      >
    >,
  ) => void;
};

function releaseLocalAssetUrls(job: VideoJob | null): void {
  if (!job) return;
  const seen = new Set<string>();
  for (const beat of job.beats) {
    for (const asset of beat.candidates) {
      // Local blob URLs we created: user-library uploads and recorded animated
      // text cards. Stock clips are remote http URLs (nothing to revoke).
      if (asset.source !== "yours" && asset.source !== "animated") continue;
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
    removeSilence: false,
    removeFillers: false,
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
    // Tighten-audio toggles are local choices; keep them across polls. Silence
    // spans are server-derived, so take fresh data when present.
    removeSilence: prev.removeSilence,
    removeFillers: prev.removeFillers,
    silenceSpans: incoming.silenceSpans ?? prev.silenceSpans,
    // Theme stickiness. A vibe is ONLY ever produced by an explicit user choice
    // — the server never invents one and reports the default {mode:"script"}
    // until /prepare persists the pick. There's a window right after the user
    // commits where in-flight polls still carry that stale "script" default; if
    // we trusted it we'd clobber the chosen vibe (e.g. on the pick-clips screen,
    // where awaitingSetup is already false). So never let a non-vibe reading
    // overwrite a locally-chosen vibe; otherwise take the incoming theme.
    theme:
      prev.theme?.mode === "vibe" && incoming.theme?.mode !== "vibe"
        ? prev.theme
        : incoming.theme ?? prev.theme,
    // Once the user commits output choices we own these flags locally so a
    // mid-flight poll (server still at "transcribed") can't bounce us back.
    prepared: prev.prepared || incoming.prepared,
    awaitingSetup: prev.prepared ? false : incoming.awaitingSetup,
    fileName: prev.fileName ?? incoming.fileName,
    durationSec: incoming.durationSec ?? prev.durationSec,
    audioUrl: prev.audioUrl ?? incoming.audioUrl,
    isVideo: incoming.isVideo ?? prev.isVideo,
    // Once the user opts in, don't let a stale poll flip this back to true.
    skipClipSearch:
      prev.skipClipSearch === false ? false : incoming.skipClipSearch ?? prev.skipClipSearch,
    // Once the upload finishes, don't let a stale poll flip the gate back on.
    uploadPending:
      prev.uploadPending === false ? false : incoming.uploadPending ?? prev.uploadPending,
  };
}

function preserveLocalJobState(prev: VideoJob, incoming: VideoJob): VideoJob {
  return {
    ...incoming,
    aspect: prev.aspect,
    quality: prev.quality,
    captions: prev.captions,
    music: prev.music,
    removeSilence: prev.removeSilence,
    removeFillers: prev.removeFillers,
    silenceSpans: incoming.silenceSpans ?? prev.silenceSpans,
    theme: prev.theme,
    prepared: prev.prepared || incoming.prepared,
    awaitingSetup: prev.prepared ? false : incoming.awaitingSetup,
    fileName: prev.fileName ?? incoming.fileName,
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

    findBrollForAll: async () => {
      const { job } = get();
      if (!job?.isVideo || !job.skipClipSearch) return;
      set({
        job: {
          ...job,
          skipClipSearch: false,
          stage: "Finding b-roll",
          beats: job.beats.map((b) =>
            b.included && b.visualType !== "text_card"
              ? { ...b, loading: true, candidates: b.candidates }
              : b,
          ),
        },
      });
      try {
        await searchAllClips(job.id);
      } catch (e) {
        const current = get().job;
        if (current?.id === job.id) {
          set({
            job: {
              ...current,
              skipClipSearch: true,
              error: e instanceof Error ? e.message : "Could not start b-roll search.",
            },
          });
        }
        throw e;
      }
    },

    render: async () => {
      const { job } = get();
      if (!job || keptBeats(job).length === 0) return;
      // Edit-while-uploading: the full video is still uploading in the
      // background, so the backend would reject the render (and we'd otherwise
      // encode from the low-fidelity transcription WAV). Surface a clear hint
      // instead of failing the render.
      if (job.uploadPending) {
        set({
          job: {
            ...job,
            error: "The video is still uploading. Rendering starts once it finishes.",
          },
        });
        return;
      }
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
        removeSilence: job.removeSilence,
        removeFillers: job.removeFillers,
      };
      try {
        await startRender(job.id, settings, renderOverrides(job), renderExcluded(job));
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

    toggleBeat: (beatIndex) => {
      const { job } = get();
      if (!job) return;
      set({
        job: mutateBeat(job, beatIndex, (b) => ({ ...b, included: !b.included })),
      });
    },

    setAllBeatsIncluded: (included) => {
      const { job } = get();
      if (!job) return;
      set({ job: { ...job, beats: job.beats.map((b) => ({ ...b, included })) } });
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

    insertAnimatedBeat: async (position, text, durationS, blob, config, words) => {
      const { job } = get();
      if (!job) return;
      await insertAnimatedBeatApi(job.id, position, text, durationS, blob, config, words);
      const incoming = await getVideoJob(job.id);
      const current = get().job ?? job;
      set({ job: preserveLocalJobState(current, incoming) });
    },

    setOverlay: (beatIndex, overlay) => {
      const { job } = get();
      if (!job) return;
      set({ job: mutateBeat(job, beatIndex, (b) => ({ ...b, overlay })) });
    },

    editBeatText: async (beatIndex, text) => {
      const { job } = get();
      if (!job) return;
      const beat = job.beats.find((b) => b.index === beatIndex);
      if (!beat) return;
      const clean = text.trim();
      if (!clean || clean === beat.text) return;

      const prevText = beat.text;
      const prevWords = beat.words;
      // Optimistic: captions/text update instantly; per-word timing is re-mapped
      // when the word count is unchanged (a pure typo fix).
      set({
        job: mutateBeat(job, beatIndex, (b) => ({
          ...b,
          text: clean,
          words: resyncWords(b.words, clean),
        })),
      });

      try {
        const res = await updateBeatTextApi(job.id, beatIndex, clean, prevWords);
        const current = get().job;
        if (!current) return;
        set({
          job: mutateBeat(current, beatIndex, (b) => ({
            ...b,
            text: res.text,
            words: res.words.length > 0 ? res.words : b.words,
          })),
        });
      } catch {
        // Roll back to the original text on failure.
        const current = get().job;
        if (current) {
          set({
            job: mutateBeat(current, beatIndex, (b) => ({
              ...b,
              text: prevText,
              words: prevWords,
            })),
          });
        }
        return;
      }

      // Animated text cards bake the text into a recorded video clip (and their
      // burned captions are suppressed), so a text-only edit is invisible. When
      // the corrected beat's chosen visual is such a card, re-record it with the
      // corrected text — same style/sound/duration — so the fix is actually seen.
      await get().rerecordAnimatedCard(beatIndex);
    },

    rerecordAnimatedCard: async (beatIndex) => {
      const job = get().job;
      if (!job) return;
      const beat = job.beats.find((b) => b.index === beatIndex);
      if (!beat) return;
      const asset = findChosenAsset(beat);
      if (!asset || asset.source !== "animated" || !asset.animated) return;

      const recorder = await import("./animated-recorder");
      if (!recorder.animatedRecordingSupported()) return;

      const isInsert = (beat.kind ?? "narration") === "insert";
      const durationS = Math.max(
        0.6,
        isInsert ? beat.durationS ?? beat.to - beat.from : beat.to - beat.from,
      );
      // Build the card's words from the CORRECTED text. When the word count is
      // unchanged we keep the original per-word timing (a true typo fix); if the
      // count changed we evenly distribute the new words across the duration so
      // the card always shows the fixed text rather than stale word data.
      const tokens = beat.text.trim().split(/\s+/).filter(Boolean);
      const timed = (beat.words ?? []).filter((w) => w.text.trim());
      let words: RelWord[];
      if (tokens.length > 0 && timed.length === tokens.length) {
        const base = isInsert ? 0 : beat.from;
        words = timed.map((w, i) => ({
          text: tokens[i],
          from: Math.max(0, w.from - base),
          to: Math.max(0, w.to - base),
        }));
      } else {
        const span = tokens.length ? durationS / tokens.length : durationS;
        words = tokens.map((t, i) => ({ text: t, from: i * span, to: (i + 1) * span }));
      }
      const dims = ASPECT_DIMS[job.aspect];
      try {
        const { blob } = await recorder.recordAnimatedClip({
          width: dims.w,
          height: dims.h,
          config: asset.animated,
          words,
          durationS,
        });
        const newAsset = await uploadAnimatedClipApi(
          job.id,
          beatIndex,
          blob,
          asset.animated,
        );
        get().addCandidate(beatIndex, newAsset, true);
      } catch {
        // Re-record failed — the text is still corrected in the transcript; the
        // old card stays so the user can retry from the clip picker.
      }
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
  if (!b.included) return false;
  if (b.visualType === "text_card") return !(b.overlay && b.overlay.trim().length > 0);
  return !b.chosenAssetId;
}

export function keptBeats(job: VideoJob | null): Beat[] {
  if (!job) return [];
  return job.beats.filter((b) => b.included);
}

// Kept gap after each shortened pause (seconds). Mirrors MIN_SILENCE_KEEP_S in
// app/timeline.py so the previewed duration matches the rendered output.
const MIN_SILENCE_KEEP_S = 0.3;

/** Subtract `cuts` intervals from `base` intervals (mirrors app/timeline.py). */
function subtractSpans(
  base: [number, number][],
  cuts: [number, number][],
): [number, number][] {
  if (cuts.length === 0) return base.filter(([s, e]) => e > s);
  const merged = [...cuts]
    .map(([s, e]) => [Math.min(s, e), Math.max(s, e)] as [number, number])
    .sort((a, b) => a[0] - b[0])
    .reduce<[number, number][]>((acc, [s, e]) => {
      const last = acc[acc.length - 1];
      if (last && s <= last[1]) last[1] = Math.max(last[1], e);
      else acc.push([s, e]);
      return acc;
    }, []);
  const out: [number, number][] = [];
  for (const [segStart, segEnd] of base) {
    let cursor = segStart;
    for (const [cutStart, cutEnd] of merged) {
      if (cutEnd <= cursor || cutStart >= segEnd) continue;
      if (cutStart > cursor) out.push([cursor, Math.min(cutStart, segEnd)]);
      cursor = Math.max(cursor, cutEnd);
      if (cursor >= segEnd) break;
    }
    if (cursor < segEnd) out.push([cursor, segEnd]);
  }
  return out.filter(([s, e]) => e > s);
}

/**
 * Output video duration in seconds for the CURRENT selection, mirroring the
 * orchestrator's timeline math (see app/timeline.py): each kept beat's window
 * runs from its own start to the next beat's start (gapless), unless "remove
 * silences" is on (then only the spoken span counts and detected pauses are
 * cut), and "remove fillers" further drops flagged words. Equals the full
 * narration length when nothing is excluded or tightened.
 */
export function renderDurationSec(job: VideoJob | null): number {
  if (!job || job.beats.length === 0) return 0;
  const beats = [...job.beats].sort((a, b) => a.index - b.index);
  const narration = beats.filter((b) => (b.kind ?? "narration") !== "insert");
  if (narration.length === 0) {
    return beats
      .filter((b) => b.included)
      .reduce((sum, b) => sum + Math.max(0.2, b.durationS ?? b.to - b.from), 0);
  }
  const audioEnd = Math.max(...narration.map((b) => b.to));
  const boundaries: number[] = [0];
  for (let i = 1; i < narration.length; i++) boundaries.push(narration[i].from);
  boundaries.push(Math.max(audioEnd, narration[narration.length - 1].to));
  for (let i = 1; i < boundaries.length; i++) {
    if (boundaries[i] < boundaries[i - 1]) boundaries[i] = boundaries[i - 1];
  }
  const silenceSpans = (job.silenceSpans ?? []) as [number, number][];
  let total = 0;
  let narrationPos = 0;
  for (const beat of beats) {
    if ((beat.kind ?? "narration") === "insert") {
      if (!beat.included) continue;
      total += Math.max(0.2, beat.durationS ?? beat.to - beat.from);
      continue;
    }
    const i = narrationPos;
    narrationPos += 1;
    if (!beat.included) continue;
    // Always the gapless boundary window; "remove silences" only shortens
    // detected pauses to a small kept gap (mirrors app/timeline.py).
    const base: [number, number][] = [[boundaries[i], boundaries[i + 1]]];
    const cuts: [number, number][] = [];
    if (job.removeSilence) {
      for (const [ss, se] of silenceSpans) {
        const cutStart = ss + MIN_SILENCE_KEEP_S;
        if (se > cutStart) cuts.push([cutStart, se]);
      }
    }
    if (job.removeFillers && beat.words) {
      for (const w of beat.words) if (w.filler) cuts.push([w.from, w.to]);
    }
    const spans = cuts.length ? subtractSpans(base, cuts) : base;
    for (const [s, e] of spans) total += Math.max(0, e - s);
  }
  return total;
}

export function chosenCount(job: VideoJob | null): { chosen: number; total: number } {
  if (!job) return { chosen: 0, total: 0 };
  const active = keptBeats(job);
  const total = active.length;
  const chosen = active.filter((b) => !beatNeedsChoice(b) && !b.loading).length;
  return { chosen, total };
}

export function renderExcluded(job: VideoJob | null): number[] {
  if (!job) return [];
  return job.beats.filter((b) => !b.included).map((b) => b.index);
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
