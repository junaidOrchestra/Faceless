import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";
import type { Word } from "./types";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/**
 * Re-map corrected beat text onto existing per-word timings (a typo fix).
 *
 * When `text` splits into the same number of whitespace tokens as `words`, return
 * a new array with each word's text swapped but its timing + filler flag kept.
 * Otherwise (a word was added/removed) leave the words untouched — captions render
 * from the beat text regardless, so they still update. Mirrors the backend's
 * `_resync_words` so optimistic and server state agree.
 */
export function resyncWords(words: Word[] | undefined, text: string): Word[] | undefined {
  if (!words || words.length === 0) return words;
  const tokens = text.trim().split(/\s+/).filter(Boolean);
  if (tokens.length !== words.length) return words;
  return words.map((w, i) => ({ ...w, text: tokens[i] }));
}

/** Format seconds as m:ss (e.g. 0:05). */
export function fmtTime(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds));
  const m = Math.floor(s / 60);
  const rem = s % 60;
  return `${m}:${rem.toString().padStart(2, "0")}`;
}

/** Format a beat time range, e.g. "0:05–0:09". */
export function fmtRange(from: number, to: number): string {
  return `${fmtTime(from)}\u2013${fmtTime(to)}`;
}

export function sleep(ms: number): Promise<void> {
  return new Promise((r) => setTimeout(r, ms));
}
