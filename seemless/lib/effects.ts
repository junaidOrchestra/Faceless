// Catalogs + synthesized SFX for short "effect" inserts.
//
// An effect insert reuses the kind="insert" beat pipeline: a brief fixed-length
// clip recorded in-browser (real overlay footage, or the previous beat's frozen
// frame) with one synthesized SFX mixed in. There are two independent choices —
// a SOUND and a VISUAL — and at least one must be set:
//
//   * VISUAL  -> a real stock-overlay clip (light leak, film burn, glitch,
//                bokeh, ...). These are PRE-FETCHED server-side from a
//                royalty-free source and stored in the DB, then served via
//                getEffectOverlays() — no live, per-effect clip search. The
//                `query` below is the canonical phrase the seeder uses
//                (orchestrator/seed_effect_overlays.py mirrors it).
//   * SOUND   -> synthesized with the Web Audio API (no sample files, no
//                licensing), routed to a caller destination — speakers for the
//                preview, a MediaStreamDestination for the recorded clip.
//
// `scheduleEffectSfx` keeps the same signature so real royalty-free samples
// (e.g. Freesound CC) can be swapped in later.

import type { EffectSoundId, EffectVisualId } from "./types";

export type EffectSoundDef = {
  id: EffectSoundId;
  label: string;
  description: string;
};

export type EffectVisualDef = {
  id: EffectVisualId;
  label: string;
  description: string;
  /** Canonical phrase the server-side seeder uses to pre-fetch overlays. */
  query: string;
  /** Clip length in seconds (short — these sit between beats). */
  durationS: number;
};

// Ordered safe/everyday first, loud/comedic last (a nudge toward restraint).
export const EFFECT_SOUNDS: EffectSoundDef[] = [
  { id: "none", label: "No sound", description: "Silent — visual only." },
  { id: "whoosh", label: "Whoosh", description: "Fast swipe — the everyday transition." },
  { id: "light_leak", label: "Soft whoosh", description: "Gentle airy swell. Smooth, cinematic." },
  { id: "zoom_punch", label: "Zoom Punch", description: "Sharp punch-in impact." },
  { id: "ding_sparkle", label: "Ding", description: "Bright chime. Highlights a key point." },
  { id: "glitch", label: "Glitch", description: "Digital static stutter. Edgy." },
  { id: "shake", label: "Impact", description: "A boom/impact thud. Lands punchlines." },
  { id: "bass_drop", label: "Bass Drop", description: "Deep cinematic bass hit." },
  { id: "record_scratch", label: "Record Scratch", description: "Vinyl scratch — the comedic interrupt." },
  { id: "vine_boom", label: "Vine Boom", description: "Iconic deep boom. Comedic emphasis." },
  { id: "air_horn", label: "Air Horn", description: "Over-the-top hype blast." },
];

// Effect inserts are deliberately VERY short punctuation between beats — a quick
// hit, not a scene. A single fixed length keeps them snappy and means the
// recorder only ever streams/records ~0.3s of overlay footage (not the whole
// clip), so adding one is fast.
export const EFFECT_DURATION_S = 0.3;

export const EFFECT_VISUALS: EffectVisualDef[] = [
  {
    id: "none",
    label: "No visual",
    description: "Sound only — freezes the previous frame while it plays.",
    query: "",
    durationS: EFFECT_DURATION_S,
  },
  {
    id: "light_leak",
    label: "Light Leak",
    description: "Warm flash of light. Smooth and cinematic.",
    query: "light leak overlay",
    durationS: EFFECT_DURATION_S,
  },
  {
    id: "film_burn",
    label: "Film Burn",
    description: "Warm analog film burn. Soft, vintage.",
    query: "film burn overlay",
    durationS: EFFECT_DURATION_S,
  },
  {
    id: "glitch",
    label: "Glitch",
    description: "Digital distortion. Edgy — tech, gaming, hype.",
    query: "glitch overlay transition",
    durationS: EFFECT_DURATION_S,
  },
  {
    id: "bokeh",
    label: "Bokeh Lights",
    description: "Soft defocused lights. Dreamy.",
    query: "bokeh lights overlay",
    durationS: EFFECT_DURATION_S,
  },
  {
    id: "particles",
    label: "Particles",
    description: "Drifting gold particles. Premium feel.",
    query: "gold particles black background",
    durationS: EFFECT_DURATION_S,
  },
  {
    id: "smoke",
    label: "Smoke",
    description: "Rolling smoke. Dramatic reveals.",
    query: "smoke black background",
    durationS: EFFECT_DURATION_S,
  },
  {
    id: "lens_flare",
    label: "Lens Flare",
    description: "A sweeping lens flare. Bright and punchy.",
    query: "lens flare overlay",
    durationS: EFFECT_DURATION_S,
  },
];

export const DEFAULT_SOUND: EffectSoundId = "whoosh";
export const DEFAULT_VISUAL: EffectVisualId = "light_leak";
/** Fallback clip length for a sound-only insert (frozen previous frame). */
export const SOUND_ONLY_DURATION_S = EFFECT_DURATION_S;

export function getSound(id: EffectSoundId): EffectSoundDef {
  return EFFECT_SOUNDS.find((s) => s.id === id) ?? EFFECT_SOUNDS[0];
}

export function getVisual(id: EffectVisualId): EffectVisualDef {
  return EFFECT_VISUALS.find((v) => v.id === id) ?? EFFECT_VISUALS[0];
}

/** Clip duration for a (visual, sound) pair. */
export function effectDuration(visual: EffectVisualId, _sound: EffectSoundId): number {
  return visual === "none" ? SOUND_ONLY_DURATION_S : getVisual(visual).durationS;
}

/** Short human label for the inserted beat (shown in the storyboard). */
export function effectLabel(visual: EffectVisualId, sound: EffectSoundId): string {
  if (visual !== "none") return getVisual(visual).label;
  if (sound !== "none") return getSound(sound).label;
  return "Effect";
}

// ---------------------------------------------------------------------------
// SFX synthesis
// ---------------------------------------------------------------------------

let noiseBuffer: AudioBuffer | null = null;
let noiseCtx: BaseAudioContext | null = null;

function getNoise(ctx: BaseAudioContext, seconds = 1): AudioBuffer {
  if (noiseBuffer && noiseCtx === ctx) return noiseBuffer;
  const len = Math.floor(ctx.sampleRate * seconds);
  const buf = ctx.createBuffer(1, len, ctx.sampleRate);
  const data = buf.getChannelData(0);
  for (let i = 0; i < len; i++) data[i] = Math.random() * 2 - 1;
  noiseBuffer = buf;
  noiseCtx = ctx;
  return buf;
}

type NoiseOpts = {
  t0: number;
  dur: number;
  gain: number;
  type?: BiquadFilterType;
  f0?: number;
  f1?: number;
  q?: number;
};

function noiseSweep(ctx: BaseAudioContext, dest: AudioNode, o: NoiseOpts): void {
  const src = ctx.createBufferSource();
  src.buffer = getNoise(ctx);
  const filt = ctx.createBiquadFilter();
  filt.type = o.type ?? "bandpass";
  filt.frequency.setValueAtTime(Math.max(20, o.f0 ?? 1000), o.t0);
  if (o.f1 != null) filt.frequency.exponentialRampToValueAtTime(Math.max(20, o.f1), o.t0 + o.dur);
  if (o.q != null) filt.Q.value = o.q;
  const g = ctx.createGain();
  g.gain.setValueAtTime(0.0001, o.t0);
  g.gain.exponentialRampToValueAtTime(o.gain, o.t0 + o.dur * 0.25);
  g.gain.exponentialRampToValueAtTime(0.0001, o.t0 + o.dur);
  src.connect(filt).connect(g).connect(dest);
  src.start(o.t0);
  src.stop(o.t0 + o.dur + 0.02);
}

type ToneOpts = {
  type: OscillatorType;
  t0: number;
  dur: number;
  f0: number;
  f1?: number;
  gain: number;
  detune?: number;
};

function tone(ctx: BaseAudioContext, dest: AudioNode, o: ToneOpts): void {
  const osc = ctx.createOscillator();
  osc.type = o.type;
  if (o.detune) osc.detune.value = o.detune;
  osc.frequency.setValueAtTime(o.f0, o.t0);
  if (o.f1 != null) osc.frequency.exponentialRampToValueAtTime(Math.max(20, o.f1), o.t0 + o.dur);
  const g = ctx.createGain();
  g.gain.setValueAtTime(0.0001, o.t0);
  g.gain.exponentialRampToValueAtTime(o.gain, o.t0 + Math.min(0.03, o.dur * 0.2));
  g.gain.exponentialRampToValueAtTime(0.0001, o.t0 + o.dur);
  osc.connect(g).connect(dest);
  osc.start(o.t0);
  osc.stop(o.t0 + o.dur + 0.02);
}

/**
 * Schedule the sound starting at `startTime` (AudioContext time). Each voice
 * self-stops. Routed to `dest` — speakers for preview, a MediaStreamDestination
 * for the recorder. No-op for "none".
 */
export function scheduleEffectSfx(
  ctx: BaseAudioContext,
  dest: AudioNode,
  id: EffectSoundId,
  startTime?: number,
): void {
  if (id === "none") return;
  const t = startTime ?? ctx.currentTime;
  switch (id) {
    case "whoosh": {
      noiseSweep(ctx, dest, { t0: t, dur: 0.45, gain: 0.45, f0: 400, f1: 3500, q: 0.7 });
      noiseSweep(ctx, dest, { t0: t + 0.05, dur: 0.4, gain: 0.25, f0: 3000, f1: 500, q: 0.6 });
      break;
    }
    case "zoom_punch": {
      noiseSweep(ctx, dest, { t0: t, dur: 0.12, gain: 0.5, type: "highpass", f0: 1200 });
      tone(ctx, dest, { type: "sine", t0: t, dur: 0.22, f0: 150, f1: 50, gain: 0.6 });
      break;
    }
    case "light_leak": {
      noiseSweep(ctx, dest, { t0: t, dur: 0.65, gain: 0.3, type: "lowpass", f0: 600, f1: 2200, q: 0.4 });
      break;
    }
    case "ding_sparkle": {
      tone(ctx, dest, { type: "sine", t0: t, dur: 0.5, f0: 1320, gain: 0.3 });
      tone(ctx, dest, { type: "sine", t0: t, dur: 0.6, f0: 880, gain: 0.22 });
      tone(ctx, dest, { type: "sine", t0: t + 0.04, dur: 0.4, f0: 2640, gain: 0.14 });
      break;
    }
    case "glitch": {
      for (let i = 0; i < 6; i++) {
        const ti = t + i * 0.08 + (i % 2 ? 0.02 : 0);
        noiseSweep(ctx, dest, {
          t0: ti,
          dur: 0.05,
          gain: 0.3,
          type: "bandpass",
          f0: 600 + i * 700,
          q: 4,
        });
        tone(ctx, dest, { type: "square", t0: ti, dur: 0.04, f0: 120 + i * 90, gain: 0.12 });
      }
      break;
    }
    case "shake": {
      tone(ctx, dest, { type: "sine", t0: t, dur: 0.35, f0: 95, f1: 40, gain: 0.7 });
      noiseSweep(ctx, dest, { t0: t, dur: 0.12, gain: 0.4, type: "lowpass", f0: 800, f1: 120 });
      break;
    }
    case "bass_drop": {
      tone(ctx, dest, { type: "sawtooth", t0: t + 0.05, dur: 0.6, f0: 80, f1: 45, gain: 0.4 });
      tone(ctx, dest, { type: "sawtooth", t0: t + 0.05, dur: 0.6, f0: 80, f1: 45, gain: 0.4, detune: 12 });
      tone(ctx, dest, { type: "sine", t0: t + 0.05, dur: 0.65, f0: 38, gain: 0.5 });
      break;
    }
    case "record_scratch": {
      const osc = ctx.createOscillator();
      osc.type = "sawtooth";
      const g = ctx.createGain();
      const bp = ctx.createBiquadFilter();
      bp.type = "bandpass";
      bp.frequency.value = 900;
      bp.Q.value = 1.5;
      osc.frequency.setValueAtTime(300, t);
      osc.frequency.linearRampToValueAtTime(800, t + 0.12);
      osc.frequency.linearRampToValueAtTime(220, t + 0.24);
      osc.frequency.linearRampToValueAtTime(620, t + 0.36);
      osc.frequency.linearRampToValueAtTime(180, t + 0.5);
      g.gain.setValueAtTime(0.0001, t);
      g.gain.exponentialRampToValueAtTime(0.45, t + 0.03);
      g.gain.exponentialRampToValueAtTime(0.0001, t + 0.55);
      osc.connect(bp).connect(g).connect(dest);
      osc.start(t);
      osc.stop(t + 0.58);
      noiseSweep(ctx, dest, { t0: t, dur: 0.5, gain: 0.18, type: "bandpass", f0: 1500, q: 2 });
      break;
    }
    case "vine_boom": {
      tone(ctx, dest, { type: "sine", t0: t, dur: 0.5, f0: 82, f1: 50, gain: 0.85 });
      tone(ctx, dest, { type: "triangle", t0: t, dur: 0.18, f0: 160, f1: 70, gain: 0.25 });
      break;
    }
    case "air_horn": {
      const blasts = [0, 0.26, 0.52];
      for (const b of blasts) {
        const tb = t + b;
        for (const f of [392, 494, 587]) {
          tone(ctx, dest, { type: "sawtooth", t0: tb, dur: 0.2, f0: f, gain: 0.18 });
          tone(ctx, dest, { type: "sawtooth", t0: tb, dur: 0.2, f0: f, gain: 0.14, detune: 14 });
        }
      }
      break;
    }
  }
}
