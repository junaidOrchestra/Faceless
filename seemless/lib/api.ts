import type {
  AnimatedTextConfig,
  Asset,
  Aspect,
  Beat,
  ContentTheme,
  Quality,
  VideoJob,
  Word,
} from "./types";
import type { RelWord } from "./animated-text";
import { makeMockBase, makeSearchResults, MOCK_LOADING_BEATS } from "./mock";
import { resyncWords, sleep } from "./utils";
import {
  orchGetVideoJob,
  orchInsertAnimatedBeat,
  orchMergeBeats,
  orchPrepare,
  orchSearchAllClips,
  orchSearchClips,
  orchSplitBeat,
  orchStartRender,
  orchUpdateBeatText,
  orchUploadAnimatedClip,
  orchUploadAudioDirect,
  orchUploadOwnClip,
} from "./orchestrator";

// ---------------------------------------------------------------------------
// API layer for the editor.
//
// By default this returns MOCK data so the app is fully usable on its own. Set
// NEXT_PUBLIC_USE_ORCHESTRATOR=1 to route every call through the Next.js proxy
// routes in app/api/* which talk to the real orchestrator (FastAPI). The
// orchestrator mapping lives in lib/orchestrator.ts.
// ---------------------------------------------------------------------------

export const USE_ORCHESTRATOR = process.env.NEXT_PUBLIC_USE_ORCHESTRATOR === "1";

// Mock pipeline timing (driven by the editor's poll loop, see lib/store.ts).
const MOCK_TRANSCRIBE_MS = 1800; // time spent "transcribing" before beats appear
const MOCK_CLIP_STEP_MS = 900; // stagger between streamed-in clip resolutions

type MockEntry = {
  base: VideoJob;
  createdAt: number;
  prepared: boolean;
  preparedAt: number | null;
  resolveAt: Map<number, number>; // beatIndex -> timestamp it finishes "searching"
};

// In-memory registry backing the mock so polling returns stable, evolving state.
const mockJobs = new Map<string, MockEntry>();
const renderStartedAt = new Map<string, number>();

function ensureMockJob(id: string, fileName?: string): MockEntry {
  let entry = mockJobs.get(id);
  if (!entry) {
    entry = {
      base: makeMockBase(id, fileName),
      createdAt: Date.now(),
      prepared: false,
      preparedAt: null,
      resolveAt: new Map<number, number>(),
    };
    mockJobs.set(id, entry);
  }
  return entry;
}

// Flip a mock job to "prepared": clip resolutions are staggered from now so the
// storyboard streams candidates in after the output setup is committed.
function mockPrepare(id: string): void {
  const entry = ensureMockJob(id);
  if (entry.prepared) return;
  entry.prepared = true;
  entry.preparedAt = Date.now();
  // The clip search can't begin until beats exist, so anchor the streamed-in
  // resolutions to whichever happens later: this prepare, or transcription
  // finishing. Lets the user commit setup *during* transcription.
  const searchStart = Math.max(entry.preparedAt, entry.createdAt + MOCK_TRANSCRIBE_MS);
  MOCK_LOADING_BEATS.forEach((idx, k) => {
    entry.resolveAt.set(idx, searchStart + (k + 1) * MOCK_CLIP_STEP_MS);
  });
}

// Derive the current state from elapsed time: transcribing (no beats) ->
// beats ready awaiting setup -> (after prepare) clips streaming in.
function mockSnapshot(entry: MockEntry): VideoJob {
  const now = Date.now();
  if (now < entry.createdAt + MOCK_TRANSCRIBE_MS) {
    // Transcribing in the background. Setup is still offered (awaitingSetup)
    // unless the user already committed it during transcription.
    return {
      ...entry.base,
      beats: [],
      status: "running",
      stage: entry.prepared ? "Finishing transcription" : "Transcribing narration",
      awaitingSetup: !entry.prepared,
      prepared: entry.prepared,
    };
  }
  if (!entry.prepared) {
    // Beats are ready to review, but the clip search is gated on output setup.
    const beats = entry.base.beats.map((b) => ({
      ...b,
      loading: b.visualType !== "text_card",
      candidates: [],
      chosenAssetId: b.visualType === "text_card" ? b.chosenAssetId : null,
    }));
    return {
      ...entry.base,
      beats,
      status: "running",
      stage: "Review & set output",
      awaitingSetup: true,
      prepared: false,
    };
  }
  const beats = entry.base.beats.map((b) => {
    const at = entry.resolveAt.get(b.index);
    if (at !== undefined && now < at) {
      return { ...b, loading: true, candidates: [], chosenAssetId: null };
    }
    return { ...b, loading: false };
  });
  const anyLoading = beats.some((b) => b.loading);
  return {
    ...entry.base,
    beats,
    status: "running",
    stage: anyLoading ? "Finding clips" : "Ready to render",
    awaitingSetup: false,
    prepared: true,
  };
}

/** POST /videos — upload narration audio (direct multipart), returns the job id. */
export async function uploadAudio(
  file: File,
  signal?: AbortSignal,
  onProgress?: (percent: number) => void,
): Promise<{ videoJobId: string }> {
  if (USE_ORCHESTRATOR) return orchUploadAudioDirect(file, signal, onProgress);

  await sleep(900); // simulate upload + 202 Accepted
  const videoJobId =
    typeof crypto !== "undefined" && "randomUUID" in crypto
      ? crypto.randomUUID().slice(0, 8)
      : Math.random().toString(36).slice(2, 10);
  ensureMockJob(videoJobId, file.name);
  return { videoJobId };
}

/** GET /videos/{id} (+ /beats) — poll the job and its storyboard. */
export async function getVideoJob(id: string): Promise<VideoJob> {
  if (USE_ORCHESTRATOR) return orchGetVideoJob(id);

  await sleep(250);
  return mockSnapshot(ensureMockJob(id));
}

export type PrepareOpts = {
  aspect: Aspect;
  quality: Quality;
  captions: boolean;
  theme: ContentTheme;
};

/**
 * POST /videos/{id}/prepare — commit the output shape and start the clip search.
 * The job pauses at "transcribed" until this is called.
 */
export async function prepareJob(jobId: string, opts: PrepareOpts): Promise<void> {
  if (USE_ORCHESTRATOR) {
    await orchPrepare(jobId, opts);
    return;
  }
  await sleep(400);
  mockPrepare(jobId);
}

/** POST /videos/{id}/clips/search-all — find stock b-roll for a video upload. */
export async function searchAllClips(jobId: string): Promise<void> {
  if (USE_ORCHESTRATOR) {
    await orchSearchAllClips(jobId);
    return;
  }
  await sleep(400);
  mockPrepare(jobId);
}

/** Picker "Search" tab — append candidate clips for a query. */
export async function searchClips(
  beatIndex: number,
  query: string,
  jobId?: string,
): Promise<Asset[]> {
  if (USE_ORCHESTRATOR && jobId) return orchSearchClips(jobId, beatIndex, query);

  await sleep(700);
  return makeSearchResults(beatIndex, query);
}

/** Picker "Your library" tab — register a user-uploaded clip as an asset. */
export async function uploadOwnClip(
  beatIndex: number,
  file: File,
  jobId?: string,
): Promise<Asset> {
  if (USE_ORCHESTRATOR && jobId) return orchUploadOwnClip(jobId, beatIndex, file);

  await sleep(800);
  const url = URL.createObjectURL(file);
  const kind = file.type.startsWith("video") ? "video" : "photo";
  return {
    id: `yours-${beatIndex}-${Date.now()}`,
    thumbUrl: kind === "video" ? "" : url,
    source: "yours",
    kind,
    mediaUrl: kind === "video" ? url : undefined,
  };
}

/**
 * Persist a recorded animated text-card clip as the chosen visual for a beat and
 * return the Asset to add to the beat's candidates.
 *
 * The returned asset's `mediaUrl` is a LOCAL blob URL (instant, always works for
 * preview); the render uses the backend-stored copy via the candidate index
 * encoded in the asset id (`o-{beat}-{candidateIndex}-animated`). In mock mode
 * (no orchestrator) it's a purely local asset.
 */
export async function uploadAnimatedClip(
  jobId: string,
  beatIndex: number,
  blob: Blob,
  config: AnimatedTextConfig,
): Promise<Asset> {
  const previewUrl = URL.createObjectURL(blob);
  if (USE_ORCHESTRATOR) {
    const { candidateIndex } = await orchUploadAnimatedClip(jobId, beatIndex, blob, config);
    return {
      id: `o-${beatIndex}-${candidateIndex}-animated`,
      thumbUrl: "",
      source: "animated",
      kind: "video",
      mediaUrl: previewUrl,
      animated: config,
    };
  }
  await sleep(300);
  return {
    id: `animated-${beatIndex}-${Date.now()}`,
    thumbUrl: "",
    source: "animated",
    kind: "video",
    mediaUrl: previewUrl,
    animated: config,
  };
}

/**
 * Insert a brand-new standalone animated text-card beat. The card has no
 * narration; the backend stores the recorded clip and splices a silent audio gap
 * of `durationS` at the insert position. Callers should re-fetch the job because
 * backend beat indices shift.
 */
export async function insertAnimatedBeat(
  jobId: string,
  position: number,
  text: string,
  durationS: number,
  blob: Blob,
  config: AnimatedTextConfig,
  words: RelWord[],
): Promise<void> {
  if (USE_ORCHESTRATOR) {
    await orchInsertAnimatedBeat(jobId, position, text, durationS, blob, config, words);
    return;
  }

  await sleep(300);
  const entry = ensureMockJob(jobId);
  const previewUrl = URL.createObjectURL(blob);
  const insertAt = Math.max(0, Math.min(position, entry.base.beats.length));
  const assetId = `animated-insert-${Date.now()}`;
  const anchor =
    insertAt < entry.base.beats.length
      ? entry.base.beats[insertAt].from
      : Math.max(0, ...entry.base.beats.map((b) => b.to));
  const inserted: Beat = {
    index: insertAt,
    from: anchor,
    to: anchor + durationS,
    text,
    visualType: "text_card",
    overlay: text.slice(0, 60),
    loading: false,
    included: true,
    chosenAssetId: assetId,
    candidates: [
      {
        id: assetId,
        thumbUrl: "",
        source: "animated",
        kind: "video",
        mediaUrl: previewUrl,
        animated: config,
      },
    ],
    words: words.map((w) => ({ text: w.text, from: w.from, to: w.to, filler: false })),
    kind: "insert",
    durationS,
  };
  entry.base = {
    ...entry.base,
    beats: [
      ...entry.base.beats.slice(0, insertAt),
      inserted,
      ...entry.base.beats.slice(insertAt).map((b) => ({ ...b, index: b.index + 1 })),
    ],
  };
}

/**
 * Correct a beat's transcript text (a typo fix). Only the caption text changes —
 * timing, audio, and clips are untouched. Returns the corrected text plus the
 * re-synced per-word timing (when the word count is unchanged). `currentWords`
 * seeds the mock/offline path; the orchestrator returns authoritative words.
 */
export async function updateBeatText(
  jobId: string,
  beatIndex: number,
  text: string,
  currentWords?: Word[],
): Promise<{ text: string; words: Word[] }> {
  const clean = text.trim();
  if (USE_ORCHESTRATOR) {
    return orchUpdateBeatText(jobId, beatIndex, clean);
  }
  await sleep(150);
  const entry = ensureMockJob(jobId);
  const beat = entry.base.beats.find((b) => b.index === beatIndex);
  const words = resyncWords(currentWords ?? beat?.words, clean) ?? [];
  if (beat) {
    entry.base = {
      ...entry.base,
      beats: entry.base.beats.map((b) =>
        b.index === beatIndex ? { ...b, text: clean, words } : b,
      ),
    };
  }
  return { text: clean, words };
}

/**
 * Split a narration beat into two at ``wordIndex`` (the first word of the second
 * half). Beats after the split shift up by one; callers re-fetch the job. The
 * mock/offline path has no split endpoint, so it's a no-op there.
 */
export async function splitBeat(
  jobId: string,
  beatIndex: number,
  wordIndex: number,
): Promise<{ firstIndex: number; secondIndex: number }> {
  if (USE_ORCHESTRATOR) {
    return orchSplitBeat(jobId, beatIndex, wordIndex);
  }
  await sleep(150);
  return { firstIndex: beatIndex, secondIndex: beatIndex + 1 };
}

/**
 * Merge a narration beat with the one after it. Beats after the pair shift down
 * by one; callers re-fetch the job. No-op on the mock/offline path.
 */
export async function mergeBeats(
  jobId: string,
  beatIndex: number,
): Promise<{ beatIndex: number }> {
  if (USE_ORCHESTRATOR) {
    return orchMergeBeats(jobId, beatIndex);
  }
  await sleep(150);
  return { beatIndex };
}

export type RenderSettings = {
  aspect: Aspect;
  captions: boolean;
  music: boolean;
  removeSilence: boolean;
  removeFillers: boolean;
};

/** POST /videos/{id}/render — kick off the final render.
 *
 * `overrides` (beat index -> chosen candidate index) is batched into this one
 * call so the encoded video uses the editor's clip swaps. See docs/IMPROVEMENTS.md.
 */
export async function startRender(
  jobId: string,
  settings: RenderSettings,
  overrides?: Record<number, number>,
  excludedBeats?: number[],
): Promise<void> {
  if (USE_ORCHESTRATOR) {
    await orchStartRender(jobId, {
      overrides,
      excludedBeats,
      aspect: settings.aspect,
      captions: settings.captions,
      removeSilence: settings.removeSilence,
      removeFillers: settings.removeFillers,
    });
    return;
  }
  await sleep(400);
  renderStartedAt.set(jobId, Date.now());
}

export type RenderStatus = {
  status: VideoJob["status"];
  stage: string;
  percent: number;
  resultUrl?: string;
};

const RENDER_STAGES = [
  "Preparing timeline",
  "Downloading clips",
  "Encoding segments",
  "Stitching video",
  "Finalizing",
];

/** GET /videos/{id} — poll render progress (mock climbs to 100%). */
export async function getRenderStatus(jobId: string): Promise<RenderStatus> {
  if (USE_ORCHESTRATOR) {
    const job = await orchGetVideoJob(jobId);
    return {
      status: job.status,
      stage: job.stage,
      percent: job.percent,
      resultUrl: job.resultUrl,
    };
  }

  await sleep(450);
  const started = renderStartedAt.get(jobId) ?? Date.now();
  const elapsed = Date.now() - started;
  const TOTAL = 7000; // ~7s mock render
  const percent = Math.min(100, Math.round((elapsed / TOTAL) * 100));
  const stageIdx = Math.min(
    RENDER_STAGES.length - 1,
    Math.floor((percent / 100) * RENDER_STAGES.length),
  );
  if (percent >= 100) {
    return {
      status: "done",
      stage: "Done",
      percent: 100,
      resultUrl: `/api/videos/${jobId}/download`,
    };
  }
  return { status: "running", stage: RENDER_STAGES[stageIdx], percent };
}
