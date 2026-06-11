// Shared, deterministic canvas renderer for animated "text card" beats.
//
// Both the live editor preview and the offscreen recorder draw frames through
// `drawAnimatedFrame`, so what the user previews is exactly what gets recorded
// and uploaded for the backend to use as the beat's footage. Everything here is
// a pure function of (clock, config, words) — no randomness — so a given beat
// renders identically every time.

import type { AnimatedSound, AnimatedTextSpeed, AnimatedTextStyle, Aspect, Word } from "./types";

// Output dimensions per aspect (mirrors orchestrator/app/formats.py). Animated
// cards are recorded at this aspect; the backend cover-scales to final output.
export const ASPECT_DIMS: Record<Aspect, { w: number; h: number }> = {
  "9:16": { w: 1080, h: 1920 },
  "16:9": { w: 1920, h: 1080 },
  "1:1": { w: 1080, h: 1080 },
};

export type AnimatedPalette = {
  id: string;
  label: string;
  /** Background colour stops (hex). */
  colors: string[];
  /** Spoken/idle text colour. */
  text: string;
  /** Currently-spoken word colour. */
  accent: string;
};

// A small curated set. Gradient/solid use `colors` as stops/base; paper and
// newspaper use their own fixed look but borrow `accent` for the active word.
export const ANIMATED_PALETTES: AnimatedPalette[] = [
  { id: "sunset", label: "Sunset", colors: ["#3a1c71", "#d76d77", "#ffaf7b"], text: "#ffffff", accent: "#ffe600" },
  { id: "ocean", label: "Ocean", colors: ["#0f2027", "#203a43", "#2c5364"], text: "#ffffff", accent: "#42e6c8" },
  { id: "grape", label: "Grape", colors: ["#41295a", "#2f0743"], text: "#ffffff", accent: "#ff7ad9" },
  { id: "forest", label: "Forest", colors: ["#093028", "#237a57"], text: "#ffffff", accent: "#c6ff7a" },
  { id: "mono", label: "Mono", colors: ["#0b0b0d", "#23232a"], text: "#ffffff", accent: "#ffe600" },
  { id: "ember", label: "Ember", colors: ["#16222a", "#3a6073"], text: "#ffffff", accent: "#ff8a3c" },
];

export const ANIMATED_STYLES: { id: AnimatedTextStyle; label: string }[] = [
  { id: "gradient", label: "Gradient" },
  { id: "paper", label: "Paper" },
  { id: "newspaper", label: "Newspaper" },
  { id: "solid_kenburns", label: "Solid + zoom" },
];

export const ANIMATED_SOUNDS: { id: AnimatedSound; label: string }[] = [
  { id: "none", label: "None" },
  { id: "typewriter", label: "Typewriter" },
  { id: "click", label: "Click" },
  { id: "pop", label: "Pop" },
  { id: "tick", label: "Tick" },
];

export function getPalette(id: string): AnimatedPalette {
  return ANIMATED_PALETTES.find((p) => p.id === id) ?? ANIMATED_PALETTES[0];
}

export const DEFAULT_ANIMATED = {
  style: "gradient" as AnimatedTextStyle,
  palette: ANIMATED_PALETTES[0].id,
  sound: "typewriter" as AnimatedSound,
};

/** Words revealed per second for each speed preset (user-authored cards). */
export const TYPING_SPEED_WPS: Record<AnimatedTextSpeed, number> = {
  slow: 2.5,
  normal: 4,
  fast: 6.5,
};

export const TYPING_SPEED_PRESETS: { id: AnimatedTextSpeed; label: string }[] = [
  { id: "slow", label: "Slow" },
  { id: "normal", label: "Normal" },
  { id: "fast", label: "Fast" },
];

// A brief blank-background moment before the first word appears.
const TYPING_LEAD_S = 0.2;
// How long the FULL text lingers on screen after the last word is revealed,
// before the card ends and the next beat begins. Without this the card cuts to
// the next beat the instant the last word appears, which feels abrupt.
const TYPING_END_HOLD_S = 0.7;

/** Seconds spent revealing the words (excludes the lead-in and end hold). */
function typingDurationForSpeed(wordCount: number, speed: AnimatedTextSpeed): number {
  const n = Math.max(1, wordCount);
  return n / TYPING_SPEED_WPS[speed];
}

/**
 * Total card duration: a short lead, the word-reveal phase, then a hold on the
 * full text so it doesn't jump-cut to the next beat (seconds).
 */
export function durationForSpeed(wordCount: number, speed: AnimatedTextSpeed): number {
  const typing = typingDurationForSpeed(wordCount, speed);
  return Math.max(0.6, Math.min(30, TYPING_LEAD_S + typing + TYPING_END_HOLD_S));
}

/**
 * Evenly-spaced per-word timings for user-authored text at a given speed. Words
 * are revealed only within the typing phase; the card then holds the full text
 * for ``TYPING_END_HOLD_S`` (the difference between the last word's end and the
 * card duration), giving a natural pause before the next beat.
 */
export function relWordsForTextAtSpeed(text: string, speed: AnimatedTextSpeed): RelWord[] {
  const toks = text.trim().split(/\s+/).filter(Boolean);
  if (toks.length === 0) return [];
  const typing = typingDurationForSpeed(toks.length, speed);
  const span = typing / toks.length;
  return toks.map((t, i) => ({
    text: t,
    from: TYPING_LEAD_S + i * span,
    to: TYPING_LEAD_S + (i + 1) * span,
  }));
}

/** Compact wire shape for POST /beats/insert (backend WordOut). */
export function relWordsToWire(words: RelWord[]): { t: string; s: number; e: number; f: boolean }[] {
  return words.map((w) => ({ t: w.text, s: w.from, e: w.to, f: false }));
}

// How many of the most-recent words to keep on screen at once.
const VISIBLE_WORD_WINDOW = 14;

export type RelWord = { text: string; from: number; to: number };

/**
 * Words for a beat as timings RELATIVE to the beat start. Falls back to an even
 * split of the beat text across the duration when per-word timing is absent
 * (jobs transcribed before word timing existed).
 */
export function relWordsForBeat(
  words: Word[] | undefined,
  beatFrom: number,
  beatText: string,
  durationS: number,
): RelWord[] {
  const real = (words ?? []).filter((w) => w.text.trim());
  if (real.length > 0) {
    return real.map((w) => ({
      text: w.text.trim(),
      from: Math.max(0, w.from - beatFrom),
      to: Math.max(0, w.to - beatFrom),
    }));
  }
  const toks = beatText.trim().split(/\s+/).filter(Boolean);
  if (toks.length === 0) return [];
  const span = durationS / toks.length;
  return toks.map((t, i) => ({ text: t, from: i * span, to: (i + 1) * span }));
}

/** Index of the word being spoken at `clock` (relative seconds), or -1. */
export function activeRelWord(words: RelWord[], clock: number): number {
  for (let i = words.length - 1; i >= 0; i--) {
    if (clock >= words[i].from) return i;
  }
  return -1;
}

type FrameOpts = {
  width: number;
  height: number;
  style: AnimatedTextStyle;
  palette: string;
  /** Seconds since the beat started. */
  clockS: number;
  durationS: number;
  words: RelWord[];
};

function lerp(a: number, b: number, t: number): number {
  return a + (b - a) * t;
}

function paintBackground(ctx: CanvasRenderingContext2D, o: FrameOpts): void {
  const { width: w, height: h, clockS: t } = o;
  const pal = getPalette(o.palette);
  switch (o.style) {
    case "gradient": {
      // Slowly rotate the gradient axis and breathe the stop positions.
      const ang = (t * 0.18) % (Math.PI * 2);
      const cx = w / 2;
      const cy = h / 2;
      const r = Math.hypot(w, h) / 2;
      const x0 = cx + Math.cos(ang) * r;
      const y0 = cy + Math.sin(ang) * r;
      const x1 = cx - Math.cos(ang) * r;
      const y1 = cy - Math.sin(ang) * r;
      const g = ctx.createLinearGradient(x0, y0, x1, y1);
      const cols = pal.colors.length >= 2 ? pal.colors : [pal.colors[0], pal.colors[0]];
      const shift = (Math.sin(t * 0.5) + 1) / 2; // 0..1 breathing
      cols.forEach((c, i) => {
        const base = i / (cols.length - 1);
        const pos = Math.min(1, Math.max(0, base + (shift - 0.5) * 0.12));
        g.addColorStop(pos, c);
      });
      ctx.fillStyle = g;
      ctx.fillRect(0, 0, w, h);
      // Soft moving vignette highlight for depth.
      const hx = cx + Math.cos(t * 0.3) * w * 0.2;
      const hy = cy + Math.sin(t * 0.27) * h * 0.2;
      const rg = ctx.createRadialGradient(hx, hy, 0, hx, hy, Math.max(w, h) * 0.7);
      rg.addColorStop(0, "rgba(255,255,255,0.10)");
      rg.addColorStop(1, "rgba(0,0,0,0.18)");
      ctx.fillStyle = rg;
      ctx.fillRect(0, 0, w, h);
      break;
    }
    case "solid_kenburns": {
      ctx.fillStyle = pal.colors[0];
      ctx.fillRect(0, 0, w, h);
      // A large translucent disc drifts + scales (Ken-Burns feel on a solid).
      const scale = lerp(0.9, 1.15, (Math.sin(t * 0.4) + 1) / 2);
      const dx = w / 2 + Math.cos(t * 0.25) * w * 0.12;
      const dy = h / 2 + Math.sin(t * 0.21) * h * 0.12;
      const rg = ctx.createRadialGradient(dx, dy, 0, dx, dy, (Math.max(w, h) * 0.6) * scale);
      rg.addColorStop(0, withAlpha(pal.colors[1] ?? pal.accent, 0.55));
      rg.addColorStop(1, "rgba(0,0,0,0)");
      ctx.fillStyle = rg;
      ctx.fillRect(0, 0, w, h);
      break;
    }
    case "paper": {
      ctx.fillStyle = "#f3ecd9";
      ctx.fillRect(0, 0, w, h);
      // Gentle warm blobs drifting for a "living paper" feel.
      for (let i = 0; i < 3; i++) {
        const px = w * (0.3 + 0.2 * i) + Math.cos(t * (0.12 + i * 0.05)) * w * 0.08;
        const py = h * (0.35 + 0.15 * i) + Math.sin(t * (0.1 + i * 0.04)) * h * 0.08;
        const rg = ctx.createRadialGradient(px, py, 0, px, py, Math.max(w, h) * 0.35);
        rg.addColorStop(0, "rgba(193,170,120,0.16)");
        rg.addColorStop(1, "rgba(193,170,120,0)");
        ctx.fillStyle = rg;
        ctx.fillRect(0, 0, w, h);
      }
      // Subtle deterministic grain.
      drawGrain(ctx, w, h, "rgba(120,100,60,0.05)");
      break;
    }
    case "newspaper": {
      ctx.fillStyle = "#efeae0";
      ctx.fillRect(0, 0, w, h);
      // Faint newsprint columns that scroll slowly upward.
      const colW = w / 6;
      const lineGap = Math.max(7, Math.round(h * 0.013));
      const offset = (t * 12) % lineGap;
      ctx.strokeStyle = "rgba(40,40,40,0.06)";
      ctx.lineWidth = 1;
      for (let c = 0; c < 6; c++) {
        const x0 = c * colW + colW * 0.12;
        const x1 = (c + 1) * colW - colW * 0.12;
        for (let y = -offset; y < h; y += lineGap) {
          ctx.beginPath();
          ctx.moveTo(x0, y);
          ctx.lineTo(x1, y);
          ctx.stroke();
        }
      }
      // Column rules.
      ctx.strokeStyle = "rgba(40,40,40,0.10)";
      for (let c = 1; c < 6; c++) {
        ctx.beginPath();
        ctx.moveTo(c * colW, h * 0.06);
        ctx.lineTo(c * colW, h * 0.94);
        ctx.stroke();
      }
      // Masthead rules top + bottom.
      ctx.strokeStyle = "rgba(20,20,20,0.55)";
      ctx.lineWidth = Math.max(2, h * 0.004);
      for (const y of [h * 0.05, h * 0.95]) {
        ctx.beginPath();
        ctx.moveTo(w * 0.06, y);
        ctx.lineTo(w * 0.94, y);
        ctx.stroke();
      }
      drawGrain(ctx, w, h, "rgba(20,20,20,0.04)");
      break;
    }
  }
}

// Deterministic dot grain (hashed positions) so frames are reproducible.
function drawGrain(ctx: CanvasRenderingContext2D, w: number, h: number, color: string): void {
  ctx.fillStyle = color;
  const n = Math.floor((w * h) / 9000);
  let seed = 12345;
  const rand = () => {
    seed = (seed * 1103515245 + 12345) & 0x7fffffff;
    return seed / 0x7fffffff;
  };
  for (let i = 0; i < n; i++) {
    const x = rand() * w;
    const y = rand() * h;
    ctx.fillRect(x, y, 1.5, 1.5);
  }
}

function withAlpha(hex: string, a: number): string {
  const h = hex.replace("#", "");
  const n = h.length === 3 ? h.split("").map((c) => c + c).join("") : h;
  const r = parseInt(n.slice(0, 2), 16);
  const g = parseInt(n.slice(2, 4), 16);
  const b = parseInt(n.slice(4, 6), 16);
  return `rgba(${r},${g},${b},${a})`;
}

function isLightStyle(style: AnimatedTextStyle): boolean {
  return style === "paper" || style === "newspaper";
}

/** Draw one frame of an animated text card onto a 2D context. */
export function drawAnimatedFrame(ctx: CanvasRenderingContext2D, o: FrameOpts): void {
  const { width: w, height: h } = o;
  ctx.clearRect(0, 0, w, h);
  paintBackground(ctx, o);

  const pal = getPalette(o.palette);
  const light = isLightStyle(o.style);
  const idleColor = light ? "#1c1a17" : pal.text;

  const active = activeRelWord(o.words, o.clockS);
  if (active < 0 || o.words.length === 0) return;

  // Sliding window of recent words ending at the current one.
  const start = Math.max(0, active - VISIBLE_WORD_WINDOW + 1);
  const visible = o.words.slice(start, active + 1);
  const activeLocal = active - start;

  // Type scales with the short side so portrait/landscape both read well.
  const base = Math.min(w, h);
  const fontSize = Math.round(base * 0.072);
  const lineHeight = Math.round(fontSize * 1.18);
  const font = `800 ${fontSize}px Inter, system-ui, -apple-system, "Segoe UI", sans-serif`;
  ctx.font = font;
  ctx.textBaseline = "alphabetic";
  ctx.textAlign = "left";

  const maxWidth = w * 0.84;
  const spaceW = ctx.measureText(" ").width;

  // Word wrap the visible window.
  type Tok = { text: string; idx: number; width: number };
  const toks: Tok[] = visible.map((wd, i) => ({
    text: wd.text.toUpperCase(),
    idx: i,
    width: ctx.measureText(wd.text.toUpperCase()).width,
  }));
  const lines: Tok[][] = [];
  let line: Tok[] = [];
  let lineW = 0;
  for (const tk of toks) {
    const add = (line.length ? spaceW : 0) + tk.width;
    if (line.length && lineW + add > maxWidth) {
      lines.push(line);
      line = [tk];
      lineW = tk.width;
    } else {
      line.push(tk);
      lineW += add;
    }
  }
  if (line.length) lines.push(line);

  const totalH = lines.length * lineHeight;
  let y = h / 2 - totalH / 2 + fontSize;

  // Pop animation for the active word (scale settles over ~140ms).
  const activeWord = o.words[active];
  const sincePop = Math.max(0, o.clockS - activeWord.from);
  const pop = 1 + 0.18 * Math.max(0, 1 - sincePop / 0.14);

  for (const ln of lines) {
    const widths = ln.map((t) => t.width);
    const totalLineW = widths.reduce((a, b) => a + b, 0) + spaceW * (ln.length - 1);
    let x = (w - totalLineW) / 2;
    for (let i = 0; i < ln.length; i++) {
      const tk = ln[i];
      const isActive = tk.idx === activeLocal;
      ctx.save();
      // Heavy outline for legibility over any background.
      ctx.lineJoin = "round";
      ctx.miterLimit = 2;
      ctx.lineWidth = Math.max(2, fontSize * 0.14);
      ctx.strokeStyle = light ? "rgba(255,255,255,0.85)" : "rgba(0,0,0,0.85)";
      ctx.fillStyle = isActive ? pal.accent : idleColor;
      if (isActive && pop !== 1) {
        const cx = x + tk.width / 2;
        const cyy = y - fontSize * 0.35;
        ctx.translate(cx, cyy);
        ctx.scale(pop, pop);
        ctx.translate(-cx, -cyy);
      }
      ctx.strokeText(tk.text, x, y);
      ctx.fillText(tk.text, x, y);
      ctx.restore();
      x += tk.width + spaceW;
    }
    y += lineHeight;
  }
}
