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

export type AssetSource = "pexels" | "wikimedia" | "yours";

export type Asset = {
  id: string;
  thumbUrl: string;
  source: AssetSource;
  kind: "photo" | "video";
  // Streamable media file for video assets (the mp4). thumbUrl is the poster
  // frame. Absent for photos and for sources that only return a still.
  mediaUrl?: string;
};

export type Beat = {
  index: number;
  from: number; // seconds
  to: number; // seconds
  text: string;
  visualType: VisualType;
  overlay?: string; // overlay set for text_card / burned text
  loading?: boolean; // results still arriving
  chosenAssetId: string | null;
  candidates: Asset[];
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
