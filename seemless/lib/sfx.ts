// Synthesized per-word sound effects for animated text cards.
//
// Everything is generated with the Web Audio API (no sample files, no licensing)
// and routed to a caller-supplied destination node. The live preview routes to
// `ctx.destination` (speakers); the recorder routes to a
// MediaStreamAudioDestinationNode so the SFX are captured into the uploaded clip.
// Designed so real samples could be swapped in later behind the same `playSfx`.

import type { AnimatedSound } from "./types";

let noiseBuffer: AudioBuffer | null = null;
let noiseCtx: BaseAudioContext | null = null;

function getNoise(ctx: BaseAudioContext): AudioBuffer {
  if (noiseBuffer && noiseCtx === ctx) return noiseBuffer;
  const len = Math.floor(ctx.sampleRate * 0.2);
  const buf = ctx.createBuffer(1, len, ctx.sampleRate);
  const data = buf.getChannelData(0);
  for (let i = 0; i < len; i++) data[i] = Math.random() * 2 - 1;
  noiseBuffer = buf;
  noiseCtx = ctx;
  return buf;
}

/**
 * Play one SFX hit at `when` (AudioContext time; defaults to now). Returns
 * silently for "none". Each voice is short-lived and self-disconnects, so
 * triggering many in a row (one per word) stays cheap.
 */
export function playSfx(
  ctx: BaseAudioContext,
  dest: AudioNode,
  sound: AnimatedSound,
  when?: number,
): void {
  if (sound === "none") return;
  const t = when ?? ctx.currentTime;

  switch (sound) {
    case "typewriter": {
      // Filtered noise burst (the "thunk") + a faint high click (the "ting").
      const src = ctx.createBufferSource();
      src.buffer = getNoise(ctx);
      const bp = ctx.createBiquadFilter();
      bp.type = "bandpass";
      bp.frequency.value = 1800;
      bp.Q.value = 0.8;
      const g = ctx.createGain();
      g.gain.setValueAtTime(0.0001, t);
      g.gain.exponentialRampToValueAtTime(0.5, t + 0.004);
      g.gain.exponentialRampToValueAtTime(0.0001, t + 0.07);
      src.connect(bp).connect(g).connect(dest);
      src.start(t);
      src.stop(t + 0.09);

      const click = ctx.createOscillator();
      click.type = "square";
      click.frequency.setValueAtTime(2400, t);
      const cg = ctx.createGain();
      cg.gain.setValueAtTime(0.0001, t);
      cg.gain.exponentialRampToValueAtTime(0.12, t + 0.002);
      cg.gain.exponentialRampToValueAtTime(0.0001, t + 0.03);
      click.connect(cg).connect(dest);
      click.start(t);
      click.stop(t + 0.04);
      break;
    }
    case "click": {
      const osc = ctx.createOscillator();
      osc.type = "triangle";
      osc.frequency.setValueAtTime(2000, t);
      const g = ctx.createGain();
      g.gain.setValueAtTime(0.0001, t);
      g.gain.exponentialRampToValueAtTime(0.2, t + 0.002);
      g.gain.exponentialRampToValueAtTime(0.0001, t + 0.04);
      osc.connect(g).connect(dest);
      osc.start(t);
      osc.stop(t + 0.05);
      break;
    }
    case "pop": {
      const osc = ctx.createOscillator();
      osc.type = "sine";
      osc.frequency.setValueAtTime(620, t);
      osc.frequency.exponentialRampToValueAtTime(180, t + 0.09);
      const g = ctx.createGain();
      g.gain.setValueAtTime(0.0001, t);
      g.gain.exponentialRampToValueAtTime(0.3, t + 0.005);
      g.gain.exponentialRampToValueAtTime(0.0001, t + 0.12);
      osc.connect(g).connect(dest);
      osc.start(t);
      osc.stop(t + 0.14);
      break;
    }
    case "tick": {
      const osc = ctx.createOscillator();
      osc.type = "square";
      osc.frequency.setValueAtTime(1200, t);
      const bp = ctx.createBiquadFilter();
      bp.type = "highpass";
      bp.frequency.value = 800;
      const g = ctx.createGain();
      g.gain.setValueAtTime(0.0001, t);
      g.gain.exponentialRampToValueAtTime(0.16, t + 0.001);
      g.gain.exponentialRampToValueAtTime(0.0001, t + 0.025);
      osc.connect(bp).connect(g).connect(dest);
      osc.start(t);
      osc.stop(t + 0.03);
      break;
    }
  }
}
