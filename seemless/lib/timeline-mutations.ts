/**
 * Pure, instant timeline mutations — metadata only, no network.
 */

import type { Asset, Beat, Transition, VideoJob, VisualType } from "./types";

function shiftIndicesUp(beats: Beat[], fromIndex: number): Beat[] {
  return beats.map((b) =>
    b.index >= fromIndex ? { ...b, index: b.index + 1 } : b,
  );
}

/** Build a single user-footage candidate for merge/split resets. */
export function footageCandidate(job: VideoJob, beat: Beat): Asset | null {
  for (const b of job.beats) {
    for (const c of b.candidates) {
      if (c.source === "yours" && c.mediaUrl) {
        return {
          ...c,
          sourceInS: beat.from,
        };
      }
    }
  }
  const proxy = job.beats.find((b) => b.candidates.some((c) => c.source === "yours"));
  const base = proxy?.candidates.find((c) => c.source === "yours");
  if (!base?.mediaUrl) return null;
  return {
    id: `yours-${beat.index}-footage`,
    thumbUrl: base.thumbUrl,
    source: "yours",
    kind: "video",
    mediaUrl: base.mediaUrl,
    sourceInS: beat.from,
  };
}

function resetBeatToFootage(job: VideoJob, beat: Beat): Beat {
  const asset = footageCandidate(job, beat);
  if (!asset) return { ...beat, needsSuggestion: true };
  return {
    ...beat,
    visualType: "broll",
    candidates: [asset],
    chosenAssetId: asset.id,
    loading: false,
    fetching: false,
    sourceInS: undefined,
    sourceOutS: undefined,
    needsSuggestion: true,
  };
}

/** Swap a beat's visual to a chosen b-roll / stock asset (instant). */
export function applyVisualSwap(beats: Beat[], beatIndex: number, assetId: string): Beat[] {
  return beats.map((b) => {
    if (b.index !== beatIndex) return b;
    const asset = b.candidates.find((c) => c.id === assetId);
    if (!asset) return b;
    const visualType: VisualType =
      asset.source === "animated" ? "text_card" : asset.kind === "photo" ? "broll" : "broll";
    return {
      ...b,
      chosenAssetId: assetId,
      visualType,
      loading: false,
      needsSuggestion: false,
    };
  });
}

/** Apply a static text card overlay to a beat (instant). */
export function applyTextCard(beats: Beat[], beatIndex: number, overlay: string): Beat[] {
  const clean = overlay.trim();
  return beats.map((b) =>
    b.index === beatIndex
      ? {
          ...b,
          visualType: "text_card" as const,
          overlay: clean,
          chosenAssetId: null,
          needsSuggestion: true,
        }
      : b,
  );
}

/** Set or clear a trailing transition on a beat (instant). */
export function applyTransition(
  beats: Beat[],
  beatIndex: number,
  transition: Transition | null,
): Beat[] {
  return beats.map((b) =>
    b.index === beatIndex ? { ...b, transitionOut: transition } : b,
  );
}

/** Toggle beat inclusion (`selected` in the timeline model). */
export function toggleIncluded(beats: Beat[], beatIndex: number): Beat[] {
  return beats.map((b) =>
    b.index === beatIndex ? { ...b, included: !b.included } : b,
  );
}

/** Merge beat ``index`` with the next narration beat (instant, client-side). */
export function mergeBeatsClient(job: VideoJob, index: number): Beat[] | null {
  const beats = [...job.beats].sort((a, b) => a.index - b.index);
  const first = beats.find((b) => b.index === index);
  const second = beats.find((b) => b.index === index + 1);
  if (!first || !second) return null;
  if ((first.kind ?? "narration") !== "narration" || (second.kind ?? "narration") !== "narration") {
    return null;
  }

  let merged: Beat = {
    ...first,
    text: `${first.text} ${second.text}`.trim(),
    words: [...(first.words ?? []), ...(second.words ?? [])],
    to: second.to,
    transitionOut: first.transitionOut ?? null,
    sourceInS: undefined,
    sourceOutS: undefined,
  };
  merged = resetBeatToFootage(job, merged);

  const withoutSecond = beats.filter((b) => b.index !== index + 1);
  return withoutSecond
    .map((b) => {
      if (b.index === index) return merged;
      if (b.index > index + 1) return { ...b, index: b.index - 1 };
      return b;
    })
    .sort((a, b) => a.index - b.index);
}

/** Split a beat at a word boundary (instant, client-side). */
export function splitBeatClient(
  job: VideoJob,
  index: number,
  wordIndex: number,
): Beat[] | null {
  const beats = [...job.beats].sort((a, b) => a.index - b.index);
  const beat = beats.find((b) => b.index === index);
  if (!beat || (beat.kind ?? "narration") !== "narration") return null;
  const words = beat.words ?? [];
  if (!words.length || wordIndex < 1 || wordIndex >= words.length) return null;

  const firstWords = words.slice(0, wordIndex);
  const secondWords = words.slice(wordIndex);
  const firstEnd = firstWords[firstWords.length - 1]?.to ?? beat.to;
  const secondStart = secondWords[0]?.from ?? firstEnd;
  const secondEnd = beat.to;

  const firstText = firstWords.map((w) => w.text).join(" ").trim();
  const secondText = secondWords.map((w) => w.text).join(" ").trim();

  let firstHalf: Beat = {
    ...beat,
    text: firstText,
    words: firstWords,
    to: firstEnd,
    transitionOut: null,
    sourceInS: undefined,
    sourceOutS: undefined,
  };
  let secondHalf: Beat = {
    ...beat,
    index: index + 1,
    text: secondText,
    words: secondWords,
    from: secondStart,
    to: secondEnd,
    transitionOut: beat.transitionOut ?? null,
    sourceInS: undefined,
    sourceOutS: undefined,
  };
  firstHalf = resetBeatToFootage(job, firstHalf);
  secondHalf = resetBeatToFootage(job, secondHalf);

  const shifted = shiftIndicesUp(beats.filter((b) => b.index !== index), index + 1);
  return [...shifted.filter((b) => b.index !== index), firstHalf, secondHalf].sort(
    (a, b) => a.index - b.index,
  );
}

/** Map client beat index to backend candidate index for persistence. */
export function candidateIndexForAsset(beat: Beat): number | null {
  if (!beat.chosenAssetId) return null;
  const idx = beat.candidates.findIndex((c) => c.id === beat.chosenAssetId);
  if (idx >= 0) return idx;
  const m = /^o-\d+-(\d+)-/.exec(beat.chosenAssetId);
  return m ? Number(m[1]) : null;
}
