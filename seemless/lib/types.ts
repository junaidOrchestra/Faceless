// Core data shapes for Brollio. These mirror the editor's mental model and
// are mapped to/from the orchestrator API in lib/api.ts.

import type { ContentTheme } from "./vibes";

export type { ContentTheme } from "./vibes";

export type VisualType =
  | "broll"
  | "map"
  | "archival"
  | "data"
  | "text_card"
  | "symbolic";

export type AssetSource = "pexels" | "wikimedia" | "yours" | "animated";

/**
 * Animated "text card" visual: instead of a stock clip, the browser renders a
 * moving background with the beat's narration appearing word-by-word in the
 * centre, plus an optional per-word sound. The rendered result is recorded to a
 * video and uploaded, so the final MP4 is identical to the preview.
 */
export type AnimatedTextStyle =
  | "gradient" // slowly shifting colour gradient
  | "paper" // soft paper texture with gentle drift
  | "newspaper" // newsprint look
  | "solid_kenburns"; // solid colour with a slow zoom/pan

/** Per-word sound that fires as each word appears (synthesized in-browser). */
export type AnimatedSound = "none" | "typewriter" | "click" | "pop" | "tick";

/** How fast words appear on a user-authored animated text card. */
export type AnimatedTextSpeed = "slow" | "normal" | "fast";

export type AnimatedTextConfig = {
  style: AnimatedTextStyle;
  /** Palette id (see ANIMATED_PALETTES in lib/animated-text.ts). */
  palette: string;
  sound: AnimatedSound;
};

/** Beat origin: transcript window vs user-added standalone card. */
export type BeatKind = "narration" | "insert";

export type Asset = {
  id: string;
  thumbUrl: string;
  source: AssetSource;
  kind: "photo" | "video";
  // Streamable media file for video assets (the mp4). thumbUrl is the poster
  // frame. Absent for photos and for sources that only return a still.
  mediaUrl?: string;
  // In-point for user-uploaded source video. Stock clips start at 0; the user's
  // full narration video should seek to the current beat's timestamp.
  sourceInS?: number;
  // Set when this asset is an animated text card. The editor renders it live
  // from this config; once chosen it is recorded + uploaded so the backend can
  // use the resulting clip as the beat's footage. `mediaUrl` holds the uploaded
  // clip URL after upload (absent while it's still a local-only preview choice).
  animated?: AnimatedTextConfig;
};

/** One transcribed word with timing and a filler/hesitation flag. */
export type Word = {
  text: string;
  from: number; // seconds
  to: number; // seconds
  filler: boolean; // an "um"/"uh"/"hmm"-style hesitation
};

export type Beat = {
  index: number;
  from: number; // seconds
  to: number; // seconds
  text: string;
  visualType: VisualType;
  overlay?: string; // overlay set for text_card / burned text
  loading?: boolean; // results still arriving
  /** When false, this beat is dropped from the final render (video + audio). */
  included: boolean;
  chosenAssetId: string | null;
  candidates: Asset[];
  /** Per-word timing (empty for jobs transcribed before this existed). */
  words?: Word[];
  /** "narration" (transcript) or "insert" (standalone animated text card). */
  kind?: BeatKind;
  /** On-screen duration for insert beats (seconds). */
  durationS?: number;
};

export type Aspect = "9:16" | "16:9" | "1:1";

export type Quality = "standard" | "high";

export type JobStatus = "queued" | "running" | "done" | "failed";

export type VideoJob = {
  id: string;
  status: JobStatus;
  stage: string;
  percent: number;
  beats: Beat[];
  aspect: Aspect;
  quality: Quality;
  captions: boolean;
  music: boolean;
  // "Tighten audio" options: drop detected silences/pauses, and drop filler
  // words ("um", "uh", …). Applied at render time; default off.
  removeSilence: boolean;
  removeFillers: boolean;
  // Detected silence/pause spans across the whole narration ([from, to] seconds),
  // so the editor can preview how much "remove silences" would save.
  silenceSpans?: [number, number][];
  // Content theme: "match my script" (default) or a chosen vibe. Client-only
  // until committed via POST /prepare.
  theme: ContentTheme;
  resultUrl?: string;
  // True once transcription is done but the output shape hasn't been chosen yet,
  // so the clip search is still gated (server status "transcribed").
  awaitingSetup?: boolean;
  // Set client-side once the user has committed output choices (POST /prepare),
  // so we don't bounce back to the setup phase on a subsequent poll.
  prepared?: boolean;
  // Human-readable failure reason (from the server, or set client-side when the
  // backend becomes unreachable / a job never settles).
  error?: string;
  // True when a non-terminal job has been in its current phase far longer than
  // expected — surfaced as a "taking longer than expected" hint (not a failure).
  slow?: boolean;
  // UI extras (not part of the wire contract, populated client-side).
  fileName?: string;
  durationSec?: number;
  audioUrl?: string;
};

export const VISUAL_TYPE_LABEL: Record<VisualType, string> = {
  broll: "B-roll",
  map: "Map",
  archival: "Archival",
  data: "Data",
  text_card: "Text card",
  symbolic: "Symbolic",
};
