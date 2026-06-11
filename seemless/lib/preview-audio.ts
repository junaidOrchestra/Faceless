"use client";

const audioUrls = new Map<string, string>();

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
