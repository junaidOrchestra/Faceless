import type { Beat } from "./types";

/** Snapshot of editable timeline state for undo/redo. */
export type TimelineSnapshot = {
  beats: Beat[];
};

const MAX_HISTORY = 80;

function cloneBeats(beats: Beat[]): Beat[] {
  return beats.map((b) => ({
    ...b,
    candidates: b.candidates.map((c) => ({ ...c, animated: c.animated ? { ...c.animated } : undefined })),
    words: b.words?.map((w) => ({ ...w })),
    transitionOut: b.transitionOut ? { ...b.transitionOut } : b.transitionOut,
  }));
}

export function snapshotBeats(beats: Beat[]): TimelineSnapshot {
  return { beats: cloneBeats(beats) };
}

export type EditHistory = {
  past: TimelineSnapshot[];
  future: TimelineSnapshot[];
};

export function createHistory(initial: Beat[]): EditHistory {
  return { past: [], future: [] };
}

/** Push current state onto the undo stack; clears redo. */
export function pushHistory(
  history: EditHistory,
  current: Beat[],
): EditHistory {
  const snap = snapshotBeats(current);
  const last = history.past[history.past.length - 1];
  if (last && JSON.stringify(last.beats) === JSON.stringify(snap.beats)) {
    return history;
  }
  const past = [...history.past, snap].slice(-MAX_HISTORY);
  return { past, future: [] };
}

export function canUndo(history: EditHistory): boolean {
  return history.past.length > 0;
}

export function canRedo(history: EditHistory): boolean {
  return history.future.length > 0;
}

export function undo(
  history: EditHistory,
  current: Beat[],
): { history: EditHistory; beats: Beat[] } | null {
  if (history.past.length === 0) return null;
  const past = [...history.past];
  const prev = past.pop()!;
  const present = snapshotBeats(current);
  return {
    history: { past, future: [present, ...history.future].slice(0, MAX_HISTORY) },
    beats: cloneBeats(prev.beats),
  };
}

export function redo(
  history: EditHistory,
  current: Beat[],
): { history: EditHistory; beats: Beat[] } | null {
  if (history.future.length === 0) return null;
  const future = [...history.future];
  const next = future.shift()!;
  const present = snapshotBeats(current);
  return {
    history: { past: [...history.past, present].slice(-MAX_HISTORY), future },
    beats: cloneBeats(next.beats),
  };
}
