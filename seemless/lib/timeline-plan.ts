/**
 * Build an edit-time preview plan entirely from the in-memory job JSON.
 * No server calls during playback — callers prefetch overlays/audio once.
 */

import { EFFECT_VISUALS } from "./effects";
import { findChosenAsset, keptBeats } from "./store";
import type { Asset, Beat, VideoJob, Word } from "./types";

export type PreviewLane = "footage" | "clip" | "photo" | "text";

export type PreviewSegment = {
  beatIndex: number;
  /** Start position on the output (virtual) timeline in seconds. */
  virtualStart: number;
  /** Segment length on the output timeline. */
  duration: number;
  lane: PreviewLane;
  /** Narration clock window used for captions + Web-Audio scheduling. */
  narrStart: number;
  narrEnd: number;
  /** Footage in/out (seconds in the user's source proxy). Footage lane only. */
  sourceIn: number;
  sourceOut: number;
  clipUrl?: string;
  posterUrl?: string;
  /** Stock / animated clips loop when shorter than the beat slot. */
  clipLoop: boolean;
  clipStartAt: number;
  text?: string;
  overlay?: string;
  words?: Word[];
  suppressCaptions: boolean;
  skipNarration: boolean;
  mixClipAudio: boolean;
};

export type PreviewTransition = {
  virtualStart: number;
  duration: number;
  effectId: string;
  afterBeatIndex: number;
  /** True when ``effectId`` is a synthesized SFX (no overlay footage). */
  soundOnly: boolean;
  /** Visual overlay clip URL (filled client-side from the overlay cache). */
  overlayUrl?: string;
};

export type TimelinePlan = {
  segments: PreviewSegment[];
  transitions: PreviewTransition[];
  totalDuration: number;
  /** Shared editing proxy for all user-footage beats (one seek target). */
  footageProxyUrl: string | null;
};

const VISUAL_EFFECT_IDS = new Set<string>(EFFECT_VISUALS.map((v) => v.id));

function beatDurationS(beat: Beat): number {
  const isInsert = (beat.kind ?? "narration") === "insert";
  if (isInsert) return Math.max(0.2, beat.durationS ?? beat.to - beat.from);
  return Math.max(0.05, beat.to - beat.from);
}

function resolveLane(beat: Beat, asset: ReturnType<typeof findChosenAsset>): PreviewLane {
  const isInsert = (beat.kind ?? "narration") === "insert";
  if (asset?.source === "yours" && asset.kind === "video") return "footage";
  if (asset?.kind === "video" && asset.mediaUrl) return "clip";
  if (asset?.thumbUrl || (asset?.kind === "photo" && asset.mediaUrl)) return "photo";
  if (beat.visualType === "text_card" || isInsert) return "text";
  if (asset) return asset.kind === "photo" ? "photo" : "text";
  return "text";
}

/** Locate the single shared footage proxy URL (all user-footage beats share it). */
export function resolveFootageProxyUrl(job: VideoJob): string | null {
  if (!job.isVideo) return null;
  for (const beat of job.beats) {
    const asset = findChosenAsset(beat);
    if (asset?.source === "yours" && asset.mediaUrl) return asset.mediaUrl;
    for (const c of beat.candidates) {
      if (c.source === "yours" && c.mediaUrl) return c.mediaUrl;
    }
  }
  return null;
}

export function buildTimelinePlan(job: VideoJob): TimelinePlan {
  const beats = [...keptBeats(job)].sort((a, b) => a.index - b.index);
  const segments: PreviewSegment[] = [];
  const transitions: PreviewTransition[] = [];
  let virtual = 0;
  let footageProxyUrl = resolveFootageProxyUrl(job);

  for (const beat of beats) {
    const asset = findChosenAsset(beat);
    const isInsert = (beat.kind ?? "narration") === "insert";
    const dur = beatDurationS(beat);
    const lane = resolveLane(beat, asset);
    const narrStart = isInsert ? 0 : beat.from;
    const narrEnd = isInsert ? dur : beat.to;

    const sourceIn =
      beat.sourceInS ??
      (lane === "footage" ? beat.from : asset?.sourceInS ?? 0);
    const sourceOut =
      beat.sourceOutS ??
      (lane === "footage" ? beat.to : narrEnd);

    if (lane === "footage" && asset?.mediaUrl) {
      footageProxyUrl = footageProxyUrl ?? asset.mediaUrl;
    }

    const isAnimated = asset?.source === "animated";
    segments.push({
      beatIndex: beat.index,
      virtualStart: virtual,
      duration: dur,
      lane,
      narrStart,
      narrEnd,
      sourceIn,
      sourceOut,
      clipUrl: lane === "clip" ? asset?.mediaUrl : undefined,
      posterUrl:
        lane === "photo"
          ? asset?.thumbUrl || asset?.mediaUrl
          : asset?.thumbUrl || undefined,
      clipLoop: lane === "clip" && asset?.source !== "animated",
      clipStartAt: asset?.sourceInS ?? 0,
      text: beat.text,
      overlay: beat.overlay || beat.text,
      words: beat.words,
      suppressCaptions: isAnimated || (isInsert && beat.visualType === "text_card"),
      skipNarration: isInsert,
      mixClipAudio: isAnimated,
    });

    virtual += dur;

    const tr = beat.transitionOut;
    if (tr && tr.durationS > 0) {
      const effectId = tr.effectId;
      const soundOnly = effectId === "none" || !VISUAL_EFFECT_IDS.has(effectId);
      transitions.push({
        virtualStart: virtual,
        duration: tr.durationS,
        effectId,
        afterBeatIndex: beat.index,
        soundOnly,
      });
      virtual += tr.durationS;
    }
  }

  return {
    segments,
    transitions,
    totalDuration: virtual,
    footageProxyUrl,
  };
}

/** Map a virtual-timeline position to a segment + offset within it. */
export function locateSegment(
  plan: TimelinePlan,
  virtual: number,
): { segment: PreviewSegment; offset: number } | null {
  for (const seg of plan.segments) {
    const end = seg.virtualStart + seg.duration;
    if (virtual >= seg.virtualStart && virtual < end - 1e-4) {
      return { segment: seg, offset: virtual - seg.virtualStart };
    }
  }
  const last = plan.segments[plan.segments.length - 1];
  if (last && Math.abs(virtual - (last.virtualStart + last.duration)) < 0.02) {
    return { segment: last, offset: last.duration };
  }
  return null;
}

export function locateTransition(
  plan: TimelinePlan,
  virtual: number,
): PreviewTransition | null {
  for (const tr of plan.transitions) {
    if (virtual >= tr.virtualStart && virtual < tr.virtualStart + tr.duration) {
      return tr;
    }
  }
  return null;
}

/** Segment index for a beat's virtual start (for seek / highlight). */
export function segmentIndexForBeat(plan: TimelinePlan, beatIndex: number): number {
  return plan.segments.findIndex((s) => s.beatIndex === beatIndex);
}
