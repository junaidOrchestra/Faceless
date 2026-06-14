/**
 * Debounced persistence for metadata-only timeline edits.
 * Flushes to PATCH /videos/{id}/timeline (batch) and structural POST endpoints.
 */

import type { Beat, Transition, VideoJob } from "./types";
import { candidateIndexForAsset } from "./timeline-mutations";

const DEBOUNCE_MS = 450;

export type TransitionPatch = {
  beatIndex: number;
  sourceInS?: number | null;
  sourceOutS?: number | null;
  transitionOut?: Transition | null;
  /** Which keys were explicitly set on this patch (PATCH semantics). */
  present: Set<"sourceInS" | "sourceOutS" | "transitionOut">;
};

type BatchPayload = {
  excluded_beats?: number[];
  selections: { beat_index: number; candidate_index: number }[];
  transitions: {
    beat_index: number;
    source_in_s?: number | null;
    source_out_s?: number | null;
    transition_out?: { effect_id: string; duration_s: number } | null;
  }[];
};

type StructuralOp =
  | { type: "merge"; beatIndex: number }
  | { type: "split"; beatIndex: number; wordIndex: number }
  | { type: "candidate"; beatIndex: number; asset: import("./types").Asset };

type PersistSink = {
  patchTimeline: (jobId: string, body: BatchPayload) => Promise<void>;
  mergeBeat: (jobId: string, beatIndex: number) => Promise<void>;
  splitBeat: (jobId: string, beatIndex: number, wordIndex: number) => Promise<void>;
  addCandidate: (
    jobId: string,
    beatIndex: number,
    asset: import("./types").Asset,
  ) => Promise<void>;
};

export function createTimelinePersister(sink: PersistSink) {
  let jobId: string | null = null;
  let timer: ReturnType<typeof setTimeout> | null = null;
  let excluded: number[] | undefined;
  const selections = new Map<number, number>();
  const transitions = new Map<number, TransitionPatch>();
  const structural: StructuralOp[] = [];
  let flushing = false;

  const clearTimer = () => {
    if (timer) {
      clearTimeout(timer);
      timer = null;
    }
  };

  const buildBatch = (): BatchPayload => {
    const body: BatchPayload = {
      selections: [],
      transitions: [],
    };
    if (excluded !== undefined) {
      body.excluded_beats = excluded;
    }
    for (const [beatIndex, candidateIndex] of selections) {
      body.selections.push({ beat_index: beatIndex, candidate_index: candidateIndex });
    }
    for (const tr of transitions.values()) {
      const row: BatchPayload["transitions"][number] = { beat_index: tr.beatIndex };
      if (tr.present.has("sourceInS")) row.source_in_s = tr.sourceInS ?? null;
      if (tr.present.has("sourceOutS")) row.source_out_s = tr.sourceOutS ?? null;
      if (tr.present.has("transitionOut")) {
        row.transition_out = tr.transitionOut
          ? {
              effect_id: tr.transitionOut.effectId,
              duration_s: tr.transitionOut.durationS,
            }
          : null;
      }
      body.transitions.push(row);
    }
    return body;
  };

  const flush = async () => {
    if (!jobId || flushing) return;
    flushing = true;
    clearTimer();
    const id = jobId;
    const batch = buildBatch();
    const ops = [...structural];
    excluded = undefined;
    selections.clear();
    transitions.clear();
    structural.length = 0;

    try {
      const hasBatch =
        batch.excluded_beats !== undefined ||
        batch.selections.length > 0 ||
        batch.transitions.length > 0;
      if (hasBatch) {
        await sink.patchTimeline(id, batch);
      }
      for (const op of ops) {
        if (op.type === "merge") await sink.mergeBeat(id, op.beatIndex);
        else if (op.type === "split") await sink.splitBeat(id, op.beatIndex, op.wordIndex);
        else await sink.addCandidate(id, op.beatIndex, op.asset);
      }
    } finally {
      flushing = false;
    }
  };

  const schedule = () => {
    clearTimer();
    timer = setTimeout(() => {
      void flush();
    }, DEBOUNCE_MS);
  };

  return {
    bind(job: VideoJob) {
      if (jobId !== job.id) {
        void flush();
        jobId = job.id;
        excluded = undefined;
        selections.clear();
        transitions.clear();
        structural.length = 0;
      }
    },
    flushNow: () => flush(),
    queueExclusions(beats: Beat[]) {
      excluded = beats.filter((b) => !b.included).map((b) => b.index);
      schedule();
    },
    queueSelection(beat: Beat) {
      const idx = candidateIndexForAsset(beat);
      if (idx !== null) selections.set(beat.index, idx);
      schedule();
    },
    queueTransition(patch: TransitionPatch) {
      const prev = transitions.get(patch.beatIndex);
      const present = new Set(patch.present);
      if (prev) prev.present.forEach((k) => present.add(k));
      transitions.set(patch.beatIndex, { ...prev, ...patch, present });
      schedule();
    },
    queueMerge(beatIndex: number) {
      structural.push({ type: "merge", beatIndex });
      schedule();
    },
    queueSplit(beatIndex: number, wordIndex: number) {
      structural.push({ type: "split", beatIndex, wordIndex });
      schedule();
    },
    queueNewCandidate(beatIndex: number, asset: import("./types").Asset) {
      structural.push({ type: "candidate", beatIndex, asset });
      schedule();
    },
    /** Rebuild pending batch from full job state (e.g. after undo). */
    syncFromJob(job: VideoJob) {
      jobId = job.id;
      excluded = job.beats.filter((b) => !b.included).map((b) => b.index);
      selections.clear();
      transitions.clear();
      for (const beat of job.beats) {
        const ci = candidateIndexForAsset(beat);
        if (ci !== null && beat.chosenAssetId?.startsWith("o-")) {
          selections.set(beat.index, ci);
        }
        const present = new Set<"sourceInS" | "sourceOutS" | "transitionOut">();
        if (beat.sourceInS !== undefined) present.add("sourceInS");
        if (beat.sourceOutS !== undefined) present.add("sourceOutS");
        if (beat.transitionOut !== undefined) present.add("transitionOut");
        if (present.size > 0) {
          transitions.set(beat.index, {
            beatIndex: beat.index,
            sourceInS: beat.sourceInS ?? null,
            sourceOutS: beat.sourceOutS ?? null,
            transitionOut: beat.transitionOut ?? null,
            present,
          });
        }
      }
      schedule();
    },
  };
}
