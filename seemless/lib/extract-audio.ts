"use client";

/**
 * Extract a 16 kHz mono WAV from a video (or audio) File in the browser.
 *
 * Whisper's preferred input format — tiny compared to the full upload, so we can
 * ship just this for transcription instead of re-downloading the whole video on
 * the server. Returns null when the browser can't decode the container/codec
 * (caller falls back to server-side extraction after the full upload completes).
 */

const WHISPER_SAMPLE_RATE = 16_000;
/** Skip client extraction above this duration to avoid OOM on very long files. */
const MAX_CLIENT_EXTRACT_S = 3_600;

function writeWavHeader(
  view: DataView,
  dataBytes: number,
  sampleRate: number,
  channels: number,
): void {
  const blockAlign = channels * 2;
  const byteRate = sampleRate * blockAlign;
  const writeStr = (offset: number, s: string) => {
    for (let i = 0; i < s.length; i++) view.setUint8(offset + i, s.charCodeAt(i));
  };
  writeStr(0, "RIFF");
  view.setUint32(4, 36 + dataBytes, true);
  writeStr(8, "WAVE");
  writeStr(12, "fmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, channels, true);
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, byteRate, true);
  view.setUint16(32, blockAlign, true);
  view.setUint16(34, 16, true);
  writeStr(36, "data");
  view.setUint32(40, dataBytes, true);
}

function downsampleToMono16k(buffer: AudioBuffer): Float32Array {
  const channels = buffer.numberOfChannels;
  const inRate = buffer.sampleRate;
  const inLen = buffer.length;
  const outLen = Math.max(1, Math.round(inLen * (WHISPER_SAMPLE_RATE / inRate)));
  const out = new Float32Array(outLen);

  for (let i = 0; i < outLen; i++) {
    const srcPos = (i * inRate) / WHISPER_SAMPLE_RATE;
    const idx = Math.min(inLen - 1, Math.floor(srcPos));
    let sample = 0;
    for (let ch = 0; ch < channels; ch++) {
      sample += buffer.getChannelData(ch)[idx] ?? 0;
    }
    out[i] = sample / channels;
  }
  return out;
}

function floatToPcm16(samples: Float32Array): Int16Array {
  const pcm = new Int16Array(samples.length);
  for (let i = 0; i < samples.length; i++) {
    const s = Math.max(-1, Math.min(1, samples[i]));
    pcm[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
  }
  return pcm;
}

/**
 * Try to build a Whisper-ready WAV from a local media file.
 * Returns null when extraction isn't possible in-browser.
 */
export async function tryExtractTranscribeWav(file: File): Promise<Blob | null> {
  if (typeof window === "undefined") return null;

  const Ctor: typeof AudioContext | undefined =
    window.AudioContext ??
    (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
  if (!Ctor) return null;

  let ctx: AudioContext | null = null;
  try {
    ctx = new Ctor();
    const arrayBuf = await file.arrayBuffer();
    const audioBuf = await ctx.decodeAudioData(arrayBuf.slice(0));

    if (!Number.isFinite(audioBuf.duration) || audioBuf.duration <= 0) return null;
    if (audioBuf.duration > MAX_CLIENT_EXTRACT_S) {
      console.info(
        `[extract-audio] skip client extraction (${audioBuf.duration.toFixed(0)}s > ${MAX_CLIENT_EXTRACT_S}s)`,
      );
      return null;
    }

    const mono = downsampleToMono16k(audioBuf);
    const pcm = floatToPcm16(mono);
    const dataBytes = pcm.byteLength;
    const wav = new ArrayBuffer(44 + dataBytes);
    const view = new DataView(wav);
    writeWavHeader(view, dataBytes, WHISPER_SAMPLE_RATE, 1);
    new Int16Array(wav, 44).set(pcm);

    const blob = new Blob([wav], { type: "audio/wav" });
    console.info(
      `[extract-audio] ok ${audioBuf.duration.toFixed(1)}s -> ${(blob.size / 1024).toFixed(0)} KB wav`,
    );
    return blob;
  } catch (e) {
    console.warn("[extract-audio] browser decode failed; server will extract after upload", e);
    return null;
  } finally {
    void ctx?.close();
  }
}
