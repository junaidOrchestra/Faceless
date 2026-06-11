// Records an animated text-card beat (canvas video + synthesized per-word SFX)
// into a single WebM blob, so the backend can use it as that beat's footage.
//
// The recording is REAL-TIME (a 4s beat takes ~4s) and uses the SAME
// `drawAnimatedFrame` + `playSfx` as the live preview, so the uploaded clip is
// identical to what the user previewed. Video is captured via
// canvas.captureStream(); SFX are routed into a MediaStreamAudioDestinationNode
// whose audio track is added to the recorded stream (the track always exists —
// silent for the "none" sound — so the backend can always mix a segment audio).

import type { AnimatedTextConfig } from "./types";
import { drawAnimatedFrame, type RelWord } from "./animated-text";
import { playSfx } from "./sfx";

// Cap the recorded long side; the backend cover-scales to the final output, and
// recording 1080x1920 in real time is needlessly heavy for a text card.
const MAX_LONG_SIDE = 1280;
const FPS = 30;

export function animatedRecordingSupported(): boolean {
  return (
    typeof window !== "undefined" &&
    typeof MediaRecorder !== "undefined" &&
    typeof HTMLCanvasElement !== "undefined" &&
    typeof HTMLCanvasElement.prototype.captureStream === "function"
  );
}

function pickMimeType(): string | undefined {
  // Only offer containers/codecs that carry an AUDIO track — the per-word SFX
  // live on the audio track and the backend mixes them into the narration. A
  // video-only mime (e.g. "vp8" with no opus) would silently drop the SFX, so
  // it is deliberately excluded. Plain "video/webm" lets the browser pick its
  // default codecs (Chrome => vp8/opus), which includes audio.
  const candidates = [
    "video/webm;codecs=vp9,opus",
    "video/webm;codecs=vp8,opus",
    "video/webm",
    "video/mp4",
  ];
  for (const c of candidates) {
    if (typeof MediaRecorder !== "undefined" && MediaRecorder.isTypeSupported(c)) return c;
  }
  return undefined;
}

function recordDims(width: number, height: number): { w: number; h: number } {
  const long = Math.max(width, height);
  if (long <= MAX_LONG_SIDE) return { w: width, h: height };
  const scale = MAX_LONG_SIDE / long;
  // Keep even dimensions (nicer for encoders).
  const w = Math.round((width * scale) / 2) * 2;
  const h = Math.round((height * scale) / 2) * 2;
  return { w, h };
}

export type RecordResult = { blob: Blob; mimeType: string; durationS: number };

/**
 * Render + record an animated beat to a WebM blob.
 *
 * @param width/height  target frame size (final output aspect; recording may be
 *                       scaled down — the backend cover-scales to output size).
 * @param config         style / palette / sound.
 * @param words          per-word timings RELATIVE to the beat start.
 * @param durationS      beat duration in seconds.
 */
export async function recordAnimatedClip({
  width,
  height,
  config,
  words,
  durationS,
}: {
  width: number;
  height: number;
  config: AnimatedTextConfig;
  words: RelWord[];
  durationS: number;
}): Promise<RecordResult> {
  if (!animatedRecordingSupported()) {
    throw new Error("This browser can't record the animated clip (no MediaRecorder/captureStream).");
  }
  const { w, h } = recordDims(width, height);
  const canvas = document.createElement("canvas");
  canvas.width = w;
  canvas.height = h;
  const ctx = canvas.getContext("2d");
  if (!ctx) throw new Error("Could not get a 2D canvas context.");

  // Paint the first frame before capture starts so the clip never opens blank.
  drawAnimatedFrame(ctx, {
    width: w,
    height: h,
    style: config.style,
    palette: config.palette,
    clockS: 0,
    durationS,
    words,
  });

  const AudioCtor: typeof AudioContext =
    window.AudioContext ?? (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
  const audioCtx = new AudioCtor();
  // The context MUST be running before recording, otherwise the audio clock is
  // frozen and the MediaStreamDestination captures silence (no SFX in the clip).
  // recordAnimatedClip is invoked from a click handler, so resume() is allowed.
  await audioCtx.resume().catch(() => {});
  if (audioCtx.state !== "running") {
    await new Promise((r) => setTimeout(r, 60));
    await audioCtx.resume().catch(() => {});
  }
  const audioDest = audioCtx.createMediaStreamDestination();

  const stream = canvas.captureStream(FPS);
  for (const track of audioDest.stream.getAudioTracks()) stream.addTrack(track);

  const mimeType = pickMimeType();
  const recorder = new MediaRecorder(stream, {
    ...(mimeType ? { mimeType } : {}),
    videoBitsPerSecond: 4_000_000,
    audioBitsPerSecond: 128_000,
  });
  const chunks: BlobPart[] = [];
  recorder.ondataavailable = (e) => {
    if (e.data && e.data.size > 0) chunks.push(e.data);
  };

  const done = new Promise<RecordResult>((resolve, reject) => {
    recorder.onstop = () => {
      const type = recorder.mimeType || mimeType || "video/webm";
      const blob = new Blob(chunks, { type });
      stream.getTracks().forEach((t) => t.stop());
      void audioCtx.close().catch(() => {});
      if (blob.size === 0) reject(new Error("Recording produced no data."));
      else resolve({ blob, mimeType: type, durationS });
    };
    recorder.onerror = () => reject(new Error("Recording failed."));
  });

  recorder.start();
  const perfStart = performance.now();
  // Schedule SFX on the audio clock so they land exactly on word onsets. Done
  // AFTER recorder.start() so the audio clock is aligned with the recording
  // start; the small lead keeps the first onset just inside the captured range.
  const audioStart = audioCtx.currentTime + 0.08;
  for (const word of words) {
    playSfx(audioCtx, audioDest, config.sound, audioStart + word.from);
  }
  await new Promise<void>((resolve) => {
    const loop = () => {
      const clockS = (performance.now() - perfStart) / 1000;
      drawAnimatedFrame(ctx, {
        width: w,
        height: h,
        style: config.style,
        palette: config.palette,
        clockS: Math.min(clockS, durationS),
        durationS,
        words,
      });
      if (clockS >= durationS) {
        resolve();
        return;
      }
      requestAnimationFrame(loop);
    };
    requestAnimationFrame(loop);
  });

  // Give the encoder a beat to flush the final frame, then stop.
  await new Promise((r) => setTimeout(r, 80));
  recorder.stop();
  return done;
}
