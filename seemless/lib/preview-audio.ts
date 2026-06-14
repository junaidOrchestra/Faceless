"use client";

import { loadUploadedMedia } from "./media-cache";

const audioUrls = new Map<string, string>();

// ---------------------------------------------------------------------------
// Uploaded-footage object URLs (for the local editor preview + beat thumbnails).
//
// The editor previews/edits the EXACT uploaded video from the user's machine
// rather than streaming the cloud copy: instant, works while the background
// upload is still in flight, and avoids egress. We keep a fresh object URL per
// job id. An in-session URL (created at upload) is used directly; after a
// refresh / direct visit it is rehydrated from the IndexedDB cache.
//
// IMPORTANT: these blob: URLs are DISPLAY-ONLY and must never be written into a
// beat's data or sent to the server — the canonical media_url stays the cloud
// object so the render (and any other device) resolves correctly.
// ---------------------------------------------------------------------------

const mediaUrls = new Map<string, string>();

/** Remember the uploaded file's object URL for a job (revokes any previous). */
export function rememberUploadedMedia(jobId: string, file: File): string {
  const previous = mediaUrls.get(jobId);
  if (previous) URL.revokeObjectURL(previous);
  const url = URL.createObjectURL(file);
  mediaUrls.set(jobId, url);
  return url;
}

/** In-session object URL for a job's uploaded footage (sync; undefined if none). */
export function getUploadedMediaUrl(jobId: string): string | undefined {
  return mediaUrls.get(jobId);
}

/**
 * Resolve a local object URL for a job's uploaded footage, rehydrating from the
 * IndexedDB cache when there's no in-session URL (e.g. after a refresh). Returns
 * null when no local copy exists on this device.
 */
export async function hydrateUploadedMediaUrl(jobId: string): Promise<string | null> {
  const existing = mediaUrls.get(jobId);
  if (existing) return existing;
  const file = await loadUploadedMedia(jobId);
  if (!file) return null;
  // A concurrent hydrate may have won the race while we awaited IndexedDB.
  const raced = mediaUrls.get(jobId);
  if (raced) return raced;
  const url = URL.createObjectURL(file);
  mediaUrls.set(jobId, url);
  return url;
}

export function forgetUploadedMedia(jobId: string): void {
  const url = mediaUrls.get(jobId);
  if (url) URL.revokeObjectURL(url);
  mediaUrls.delete(jobId);
}

// ---------------------------------------------------------------------------
// Narration decode cache (for the synced preview player).
//
// Decoding the narration is the expensive part of opening the preview, so we do
// it ONCE per session and reuse it everywhere. A single shared, persistent
// AudioContext is used for both decoding and playback: decoding at the playback
// sample rate avoids a costly second resample, and keeping the context alive
// avoids per-open create/teardown latency. The decoded buffer is cached by URL.
// ---------------------------------------------------------------------------

const decodedAudioCache = new Map<string, AudioBuffer>();
const decodingInFlight = new Map<string, Promise<AudioBuffer>>();
let sharedAudioCtx: AudioContext | null = null;

export function getSharedAudioCtx(): AudioContext | null {
  if (typeof window === "undefined") return null;
  if (sharedAudioCtx && sharedAudioCtx.state !== "closed") return sharedAudioCtx;
  const Ctor: typeof AudioContext | undefined =
    window.AudioContext ??
    (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
  if (!Ctor) return null;
  try {
    sharedAudioCtx = new Ctor();
  } catch {
    sharedAudioCtx = null;
  }
  return sharedAudioCtx;
}

export function getCachedNarration(url: string | undefined | null): AudioBuffer | undefined {
  if (!url) return undefined;
  return decodedAudioCache.get(url);
}

// Fetch + decode the narration, de-duplicating concurrent calls and caching the
// result. Shared by the eager prewarm and the on-open path.
export function decodeNarration(url: string): Promise<AudioBuffer> {
  const cached = decodedAudioCache.get(url);
  if (cached) return Promise.resolve(cached);
  const inflight = decodingInFlight.get(url);
  if (inflight) return inflight;
  const ctx = getSharedAudioCtx();
  if (!ctx) return Promise.reject(new Error("AudioContext unavailable"));
  const promise = fetch(url)
    .then((r) => {
      if (!r.ok) throw new Error(`audio fetch ${r.status}`);
      return r.arrayBuffer();
    })
    // slice(0) because decodeAudioData detaches the ArrayBuffer.
    .then((buf) => ctx.decodeAudioData(buf.slice(0)))
    .then((decoded) => {
      decodedAudioCache.set(url, decoded);
      return decoded;
    })
    .finally(() => {
      decodingInFlight.delete(url);
    });
  decodingInFlight.set(url, promise);
  return promise;
}

/**
 * Eagerly fetch + decode the narration so the preview opens with audio
 * immediately. Safe to call repeatedly; no-ops if already cached or in flight.
 */
export function prewarmPreviewAudio(url: string | undefined | null): void {
  if (typeof window === "undefined" || !url) return;
  if (decodedAudioCache.has(url) || decodingInFlight.has(url)) return;
  // Swallow here; the open path surfaces failures via the element fallback.
  decodeNarration(url).catch(() => {});
}

export function rememberPreviewAudio(jobId: string, file: File): string {
  const previous = audioUrls.get(jobId);
  if (previous) URL.revokeObjectURL(previous);

  const url = URL.createObjectURL(file);
  audioUrls.set(jobId, url);

  return url;
}

export function getPreviewAudioUrl(jobId: string): string | undefined {
  return audioUrls.get(jobId);
}

export function forgetPreviewAudio(jobId: string): void {
  const url = audioUrls.get(jobId);
  if (url) URL.revokeObjectURL(url);
  audioUrls.delete(jobId);
}
