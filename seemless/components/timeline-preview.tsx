"use client";

import * as React from "react";
import { Loader2, Pause, Play } from "lucide-react";
import { getEffectOverlays } from "@/lib/api";
import { spriteCropForTime } from "@/lib/footage-thumbs";
import { attachMediaSource, seekVideo } from "@/lib/hls-video";
import {
  decodeNarration,
  getCachedNarration,
  getSharedAudioCtx,
  getUploadedMediaUrl,
  hydrateUploadedMediaUrl,
  prewarmPreviewAudio,
} from "@/lib/preview-audio";
import { scheduleEffectSfx } from "@/lib/effects";
import { findChosenAsset, keptBeats } from "@/lib/store";
import {
  buildTimelinePlan,
  locateSegment,
  locateTransition,
  segmentIndexForBeat,
  type PreviewSegment,
  type TimelinePlan,
} from "@/lib/timeline-plan";
import type { Aspect, Beat, EffectSoundId, VideoJob } from "@/lib/types";
import { cn } from "@/lib/utils";

const ASPECT_STAGE: Record<Aspect, string> = {
  "9:16": "aspect-[9/16]",
  "16:9": "aspect-video",
  "1:1": "aspect-square",
};

const CAPTION_CHUNK = 4;
const CLOCK_COMMIT_MS = 80;

function splitWords(text: string): string[] {
  return text.trim().split(/\s+/).filter(Boolean);
}

function activeWordIndex(words: string[], startS: number, endS: number, clock: number): number {
  if (words.length === 0) return -1;
  const dur = Math.max(0.001, endS - startS);
  const rel = clock - startS;
  if (rel <= 0) return 0;
  if (rel >= dur) return words.length - 1;
  const weights = words.map((w) => w.length + 1);
  const total = weights.reduce((a, b) => a + b, 0);
  const target = (rel / dur) * total;
  let acc = 0;
  for (let i = 0; i < words.length; i++) {
    acc += weights[i];
    if (target < acc) return i;
  }
  return words.length - 1;
}

function activeTimedWordIndex(words: { from: number; to: number }[], clock: number): number {
  if (words.length === 0) return -1;
  for (let i = words.length - 1; i >= 0; i--) {
    if (clock >= words[i].from) return i;
  }
  return 0;
}

function SpriteBeatThumb({
  beat,
  footageThumbs,
  active,
  onClick,
}: {
  beat: Beat;
  footageThumbs?: VideoJob["footageThumbs"];
  active: boolean;
  onClick: () => void;
}) {
  const asset = findChosenAsset(beat);
  const crop =
    asset?.source === "yours"
      ? spriteCropForTime(footageThumbs, beat.sourceInS ?? beat.from)
      : null;

  return (
    <button
      type="button"
      onClick={onClick}
      title={`Beat ${beat.index + 1}`}
      className={cn(
        "relative h-14 w-[4.5rem] shrink-0 overflow-hidden rounded-md border transition-all",
        active
          ? "border-accent ring-2 ring-accent/40"
          : "border-hairline opacity-80 hover:opacity-100",
      )}
    >
      {beat.visualType === "text_card" ? (
        <div className="grid size-full place-items-center bg-gradient-to-br from-panel-raised to-canvas p-1 text-center text-[9px] font-medium leading-tight text-cream">
          <span className="line-clamp-3">{beat.overlay || beat.text.slice(0, 40)}</span>
        </div>
      ) : crop ? (
        <div
          className="size-full bg-canvas"
          style={{
            backgroundImage: `url("${crop.url}")`,
            backgroundPosition: `${crop.x}px ${crop.y}px`,
            backgroundSize: `${crop.sheetW}px ${crop.sheetH}px`,
            backgroundRepeat: "no-repeat",
          }}
        />
      ) : asset?.thumbUrl ? (
        <img src={asset.thumbUrl} alt="" className="size-full object-cover" />
      ) : (
        <div className="grid size-full place-items-center bg-panel-raised text-[9px] text-faint">
          {beat.index + 1}
        </div>
      )}
    </button>
  );
}

type AudioSeg = { narrStart: number; narrEnd: number; virtualStart: number; virtualDur: number; skip: boolean };

function buildAudioSegs(plan: TimelinePlan): AudioSeg[] {
  return plan.segments.map((s) => ({
    narrStart: s.narrStart,
    narrEnd: s.narrEnd,
    virtualStart: s.virtualStart,
    virtualDur: s.duration,
    skip: s.skipNarration,
  }));
}

export function TimelinePreview({
  job,
  seekBeatIndex = null,
  onSeekComplete,
}: {
  job: VideoJob;
  /** When set, seek playback to this beat then clear via ``onSeekComplete``. */
  seekBeatIndex?: number | null;
  onSeekComplete?: () => void;
}) {
  const plan = React.useMemo(() => buildTimelinePlan(job), [job]);
  const beats = React.useMemo(() => keptBeats(job), [job]);
  const hasContent = plan.segments.length > 0;

  // For an uploaded video, the footage <video> element IS the source of truth for
  // both picture and sound — exactly like a normal editor preview. We deliberately
  // do NOT route its audio through Web Audio: decoding a full (e.g. 145 MB) upload
  // to an AudioBuffer is slow, memory-heavy, and silently fails for many codecs,
  // which is what made the preview go black + silent. Native playback keeps A/V in
  // sync for free. Web Audio narration is reserved for narration-over-broll jobs
  // (no single footage track to play), where it must follow timeline edits.
  const preferFootageAudio = Boolean(job.isVideo);

  React.useEffect(() => {
    console.info(
      `[preview] job ${job.id}: isVideo=${job.isVideo} preferFootageAudio=${preferFootageAudio} ` +
        `audioUrl=${job.audioUrl ? "set" : "none"} segments=${plan.segments.length}`,
    );
  }, [job.id, job.isVideo, preferFootageAudio, job.audioUrl, plan.segments.length]);

  // Footage source for the shared <video>. For uploaded videos this is ALWAYS the
  // browser-local file: instant in-session, and rehydrated from IndexedDB after a
  // refresh / dev restart / direct visit (see hydrateUploadedMediaUrl). We never
  // stream the cloud original for the editor preview. ``undefined`` = still
  // resolving (show spinner), ``null`` = no local copy on this device.
  const [localFootageUrl, setLocalFootageUrl] = React.useState<
    string | null | undefined
  >(() => (job.isVideo ? getUploadedMediaUrl(job.id) ?? undefined : null));

  React.useEffect(() => {
    if (!job.isVideo) {
      setLocalFootageUrl(null);
      return;
    }
    const sync = getUploadedMediaUrl(job.id);
    if (sync) {
      console.info(`[preview] job ${job.id}: footage = in-session blob`);
      setLocalFootageUrl(sync);
      return;
    }
    let cancelled = false;
    setLocalFootageUrl(undefined);
    void hydrateUploadedMediaUrl(job.id).then((url) => {
      if (cancelled) return;
      if (url) console.info(`[preview] job ${job.id}: footage = rehydrated local file`);
      else console.warn(`[preview] job ${job.id}: no local footage on this device`);
      setLocalFootageUrl(url ?? null);
    });
    return () => {
      cancelled = true;
    };
  }, [job.isVideo, job.id]);

  const footageSrc = job.isVideo ? localFootageUrl ?? null : plan.footageProxyUrl;

  const footageRef = React.useRef<HTMLVideoElement>(null);
  const clipRef = React.useRef<HTMLVideoElement>(null);
  const transitionRef = React.useRef<HTMLVideoElement>(null);
  // Which beat each <video> is currently playing, so the RAF tick only re-seeks
  // on a segment change (not every frame — that fought native playback and
  // caused the video/audio to stutter). Reset to null when the lane is hidden.
  const footageSegRef = React.useRef<number | null>(null);
  const clipSegRef = React.useRef<number | null>(null);

  const [playing, setPlaying] = React.useState(false);
  const [virtual, setVirtual] = React.useState(0);
  const [captionClock, setCaptionClock] = React.useState(0);
  const virtualRef = React.useRef(0);
  const playingRef = React.useRef(false);
  const lastSegIdxRef = React.useRef(0);
  const lastTransitionKeyRef = React.useRef<string | null>(null);

  const [audioReady, setAudioReady] = React.useState(false);
  const [webAudioFailed, setWebAudioFailed] = React.useState(false);
  const [footageLoading, setFootageLoading] = React.useState(false);
  const audioCtxRef = React.useRef<AudioContext | null>(null);
  const bufferRef = React.useRef<AudioBuffer | null>(null);
  const sourcesRef = React.useRef<AudioBufferSourceNode[]>([]);
  const anchorRef = React.useRef<
    | { virtual: number; ctxTime: number }
    | { virtual: number; perf: number; silent: true }
    | null
  >(null);

  const overlayMapRef = React.useRef<Record<string, { mediaUrl: string }[]>>({});

  const located = locateSegment(plan, virtual);
  const activeTransition = locateTransition(plan, virtual);
  const activeSegment: PreviewSegment | null =
    located?.segment ?? plan.segments[lastSegIdxRef.current] ?? null;
  const segOffset = located?.offset ?? 0;

  const activeSegIdx = located
    ? plan.segments.indexOf(located.segment)
    : activeTransition
      ? lastSegIdxRef.current
      : 0;

  React.useEffect(() => {
    if (located) lastSegIdxRef.current = plan.segments.indexOf(located.segment);
  }, [located, plan.segments]);

  // Prefetch overlay clips once (not during playback).
  React.useEffect(() => {
    void getEffectOverlays().then((map) => {
      overlayMapRef.current = map;
    });
  }, []);

  React.useEffect(() => {
    // Video uploads play their own audio track natively — skip prewarming a
    // separate narration buffer (it would fetch the whole file again).
    if (hasContent && !preferFootageAudio) prewarmPreviewAudio(job.audioUrl);
  }, [job.audioUrl, hasContent, preferFootageAudio]);

  React.useEffect(() => {
    if (!job.audioUrl || preferFootageAudio) return;
    const ctx = getSharedAudioCtx();
    audioCtxRef.current = ctx;
    if (!ctx) {
      setWebAudioFailed(true);
      return;
    }
    const cached = getCachedNarration(job.audioUrl);
    if (cached) {
      bufferRef.current = cached;
      setAudioReady(true);
      console.info(`[preview] job ${job.id}: narration decode = cached`);
      return;
    }
    decodeNarration(job.audioUrl)
      .then((buf) => {
        bufferRef.current = buf;
        setAudioReady(true);
        console.info(`[preview] job ${job.id}: narration decode ok (${buf.duration.toFixed(1)}s)`);
      })
      .catch((e) => {
        setWebAudioFailed(true);
        console.warn(`[preview] job ${job.id}: narration decode failed -> native audio`, e);
      });
  }, [job.audioUrl, preferFootageAudio, job.id]);

  // Attach the shared footage source (one element, seek per beat).
  React.useEffect(() => {
    const v = footageRef.current;
    if (!v) return;
    // Start muted; syncVideos unmutes it only when it must drive audio itself
    // (Web Audio narration unavailable). Avoids a sound blip before first sync.
    v.muted = true;
    return attachMediaSource(v, footageSrc);
  }, [footageSrc]);

  // Surface footage buffering as a spinner so a slow remote proxy/original load
  // reads as "loading" instead of a frozen black frame. ``waiting``/``loadstart``
  // mark buffering; ``canplay``/``playing``/``loadeddata`` clear it.
  React.useEffect(() => {
    const v = footageRef.current;
    if (!v || !footageSrc) {
      setFootageLoading(false);
      return;
    }
    const onBusy = () => setFootageLoading(true);
    const onReady = () => setFootageLoading(false);
    const onMeta = () =>
      console.info(
        `[preview] footage metadata: ${v.videoWidth}x${v.videoHeight} ` +
          `dur=${Number.isFinite(v.duration) ? v.duration.toFixed(1) : "?"}s`,
      );
    const onError = () =>
      console.warn(
        `[preview] footage <video> error code=${v.error?.code} msg=${v.error?.message ?? ""} ` +
          `src=${footageSrc}`,
      );
    v.addEventListener("loadstart", onBusy);
    v.addEventListener("waiting", onBusy);
    v.addEventListener("seeking", onBusy);
    v.addEventListener("canplay", onReady);
    v.addEventListener("playing", onReady);
    v.addEventListener("loadeddata", onReady);
    v.addEventListener("seeked", onReady);
    v.addEventListener("loadedmetadata", onMeta);
    v.addEventListener("error", onError);
    if (v.readyState < 2) setFootageLoading(true);
    return () => {
      v.removeEventListener("loadstart", onBusy);
      v.removeEventListener("waiting", onBusy);
      v.removeEventListener("seeking", onBusy);
      v.removeEventListener("canplay", onReady);
      v.removeEventListener("playing", onReady);
      v.removeEventListener("loadeddata", onReady);
      v.removeEventListener("seeked", onReady);
      v.removeEventListener("loadedmetadata", onMeta);
      v.removeEventListener("error", onError);
    };
  }, [footageSrc]);

  const stopSources = React.useCallback(() => {
    for (const s of sourcesRef.current) {
      try {
        s.onended = null;
        s.stop();
        s.disconnect();
      } catch {
        // already stopped
      }
    }
    sourcesRef.current = [];
  }, []);

  const scheduleNarrationFrom = React.useCallback(
    (vpos: number) => {
      const ctx = audioCtxRef.current;
      const buffer = bufferRef.current;
      if (!ctx || !buffer || webAudioFailed) return false;
      stopSources();
      const anchor = ctx.currentTime + 0.04;
      anchorRef.current = { virtual: vpos, ctxTime: anchor };
      const audioSegs = buildAudioSegs(plan);
      for (const seg of audioSegs) {
        const segVirtEnd = seg.virtualStart + seg.virtualDur;
        if (segVirtEnd <= vpos + 1e-3 || seg.skip) continue;
        const segVirtStart = Math.max(seg.virtualStart, vpos);
        const within = segVirtStart - seg.virtualStart;
        const when = anchor + (segVirtStart - vpos);
        const srcOffset = seg.narrStart + within;
        const dur = seg.virtualDur - within;
        const node = ctx.createBufferSource();
        node.buffer = buffer;
        node.connect(ctx.destination);
        try {
          node.start(when, srcOffset, dur);
        } catch {
          // out of range
        }
        sourcesRef.current.push(node);
      }
      void ctx.resume().catch(() => {});
      return true;
    },
    [plan, stopSources, webAudioFailed],
  );

  // For video uploads, the footage element always drives audio (preferFootageAudio
  // short-circuits Web Audio). For narration-over-broll jobs we use the synced Web
  // Audio buffer when it decoded successfully, falling back to native audio if not.
  const narrationActive =
    !preferFootageAudio && Boolean(job.audioUrl) && audioReady && !webAudioFailed;

  // ``seek`` true => an explicit jump (scrub / segment entry / paused first
  // frame): set currentTime exactly. ``seek`` false => the RAF tick during
  // continuous playback: DON'T touch currentTime (that interrupts decode + audio
  // and stutters). We only correct then if the element drifted off a new segment
  // boundary or by a large margin — otherwise the video plays itself.
  const DRIFT_RESEEK_S = 0.35;
  const syncVideos = React.useCallback(
    (seg: PreviewSegment | null, offset: number, isPlaying: boolean, seek = true) => {
      const footage = footageRef.current;
      const clip = clipRef.current;
      const transition = transitionRef.current;

      if (footage) {
        const showFootage = seg?.lane === "footage";
        footage.style.opacity = showFootage ? "1" : "0";
        if (showFootage && seg) {
          const window = Math.max(0.05, seg.sourceOut - seg.sourceIn);
          const t = seg.sourceIn + Math.min(offset, window);
          // Mute only while the narration buffer is driving audio; otherwise let
          // the footage's native track play (avoids double audio when both work).
          footage.muted = narrationActive;
          const segChanged = footageSegRef.current !== seg.beatIndex;
          footageSegRef.current = seg.beatIndex;
          if (seek || !isPlaying || segChanged) {
            seekVideo(footage, t);
          } else if (Math.abs(footage.currentTime - t) > DRIFT_RESEEK_S) {
            seekVideo(footage, t);
          }
          if (isPlaying && footage.paused) void footage.play().catch(() => {});
          if (!isPlaying) footage.pause();
        } else {
          footageSegRef.current = null;
          if (!isPlaying) footage.pause();
        }
      }

      if (clip) {
        const showClip = seg?.lane === "clip";
        clip.style.opacity = showClip ? "1" : "0";
        if (showClip && seg?.clipUrl) {
          if (clip.src !== seg.clipUrl) clip.src = seg.clipUrl;
          clip.muted = !seg.mixClipAudio;
          // Short stock/animated clips loop natively (no per-frame re-seek).
          clip.loop = seg.clipLoop;
          const base = seg.clipStartAt + offset;
          const dur = clip.duration;
          const t =
            seg.clipLoop && dur && Number.isFinite(dur) && dur > 0
              ? base % dur
              : base;
          const segChanged = clipSegRef.current !== seg.beatIndex;
          clipSegRef.current = seg.beatIndex;
          if (seek || !isPlaying || segChanged) {
            seekVideo(clip, t);
          } else if (!seg.clipLoop && Math.abs(clip.currentTime - t) > DRIFT_RESEEK_S) {
            seekVideo(clip, t);
          }
          if (isPlaying && clip.paused) void clip.play().catch(() => {});
          if (!isPlaying) clip.pause();
        } else {
          clipSegRef.current = null;
          if (!isPlaying) clip.pause();
        }
      }

      if (transition) {
        transition.style.opacity = "0";
        transition.pause();
      }
    },
    [narrationActive],
  );

  // Paint the first beat's frame while paused so the preview shows real footage
  // (not black) the moment metadata is ready — no need to press play first. With
  // ``preload="metadata"`` the browser range-fetches just enough to render it.
  React.useEffect(() => {
    if (playing || !hasContent) return;
    const loc = locateSegment(plan, virtualRef.current);
    if (loc) syncVideos(loc.segment, loc.offset, false);
  }, [playing, hasContent, plan, footageSrc, syncVideos]);

  const playTransition = React.useCallback(
    (tr: NonNullable<ReturnType<typeof locateTransition>>, holdSeg: PreviewSegment | null) => {
      const key = `${tr.afterBeatIndex}-${tr.virtualStart}`;
      if (lastTransitionKeyRef.current === key) return;
      lastTransitionKeyRef.current = key;

      // Hold the outgoing beat's last frame underneath.
      if (holdSeg) {
        syncVideos(holdSeg, holdSeg.duration, playingRef.current);
      }

      const ctx = audioCtxRef.current;
      if (ctx) {
        scheduleEffectSfx(ctx, ctx.destination, tr.effectId as EffectSoundId);
      }

      const overlays = overlayMapRef.current[tr.effectId];
      const url = tr.overlayUrl ?? overlays?.[0]?.mediaUrl;
      const tv = transitionRef.current;
      if (tv && url && !tr.soundOnly) {
        if (tv.src !== url) tv.src = url;
        tv.style.opacity = "1";
        tv.muted = false;
        seekVideo(tv, 0);
        if (playingRef.current) void tv.play().catch(() => {});
      }
    },
    [syncVideos],
  );

  const beginPlayback = React.useCallback(
    (vpos: number) => {
      lastTransitionKeyRef.current = null;
      const useWebAudio =
        !preferFootageAudio && Boolean(job.audioUrl) && audioReady && !webAudioFailed;
      console.info(
        `[preview] play @${vpos.toFixed(2)}s audio=${useWebAudio ? "web-audio narration" : "native footage track"}`,
      );
      if (useWebAudio) {
        scheduleNarrationFrom(vpos);
      } else {
        // Footage-driven audio: a wall-clock anchor advances captions/scene sync
        // while the <video> element plays its own track at the same real rate.
        anchorRef.current = { virtual: vpos, perf: performance.now(), silent: true };
      }
      playingRef.current = true;
      setPlaying(true);
      const loc = locateSegment(plan, vpos);
      if (loc) syncVideos(loc.segment, loc.offset, true);
    },
    [preferFootageAudio, job.audioUrl, audioReady, webAudioFailed, scheduleNarrationFrom, plan, syncVideos],
  );

  const pausePlayback = React.useCallback(() => {
    const a = anchorRef.current;
    if (a && "ctxTime" in a && audioCtxRef.current) {
      virtualRef.current =
        a.virtual + (audioCtxRef.current.currentTime - a.ctxTime);
    } else if (a && "silent" in a) {
      virtualRef.current = a.virtual + (performance.now() - a.perf) / 1000;
    } else {
      virtualRef.current = virtual;
    }
    stopSources();
    playingRef.current = false;
    setPlaying(false);
    setVirtual(virtualRef.current);
    footageRef.current?.pause();
    clipRef.current?.pause();
    transitionRef.current?.pause();
    anchorRef.current = null;
  }, [stopSources, virtual]);

  const seekToVirtual = React.useCallback(
    (t: number, autoplay = false) => {
      if (!autoplay && playingRef.current) pausePlayback();

      const clamped = Math.max(0, Math.min(plan.totalDuration, t));
      virtualRef.current = clamped;
      setVirtual(clamped);
      lastTransitionKeyRef.current = null;
      const loc = locateSegment(plan, clamped);
      const tr = locateTransition(plan, clamped);
      if (loc) {
        syncVideos(loc.segment, loc.offset, autoplay);
        const narr =
          loc.segment.narrStart +
          (loc.offset / Math.max(0.001, loc.segment.duration)) *
            (loc.segment.narrEnd - loc.segment.narrStart);
        setCaptionClock(narr);
      } else if (tr) {
        const prev = plan.segments.find((s) => s.beatIndex === tr.afterBeatIndex);
        if (prev) syncVideos(prev, prev.duration, autoplay);
        playTransition(tr, prev ?? null);
      }
      if (autoplay) beginPlayback(clamped);
    },
    [plan, syncVideos, playTransition, beginPlayback, pausePlayback],
  );

  React.useEffect(() => {
    if (seekBeatIndex == null) return;
    const idx = segmentIndexForBeat(plan, seekBeatIndex);
    if (idx < 0) {
      onSeekComplete?.();
      return;
    }
    const seg = plan.segments[idx];
    seekToVirtual(seg.virtualStart, true);
    onSeekComplete?.();
  }, [seekBeatIndex, plan, seekToVirtual, onSeekComplete]);

  // RAF playback loop — drives virtual time, scene sync, transitions, captions.
  React.useEffect(() => {
    if (!playing) return;
    let raf = 0;
    let lastCommit = 0;

    const loop = () => {
      const a = anchorRef.current;
      let v = virtualRef.current;
      if (a && "ctxTime" in a && audioCtxRef.current) {
        v = a.virtual + (audioCtxRef.current.currentTime - a.ctxTime);
      } else if (a && "silent" in a) {
        v = a.virtual + (performance.now() - a.perf) / 1000;
      }
      virtualRef.current = v;

      if (v >= plan.totalDuration - 0.02) {
        pausePlayback();
        virtualRef.current = 0;
        setVirtual(0);
        return;
      }

      const loc = locateSegment(plan, v);
      const tr = locateTransition(plan, v);

      if (tr) {
        const prev = plan.segments.find((s) => s.beatIndex === tr.afterBeatIndex);
        playTransition(tr, prev ?? null);
      } else if (loc) {
        lastTransitionKeyRef.current = null;
        transitionRef.current && (transitionRef.current.style.opacity = "0");
        // seek=false: continuous tick — let the <video> play natively; syncVideos
        // only re-seeks on a segment change or large drift.
        syncVideos(loc.segment, loc.offset, true, false);

        const narr =
          loc.segment.narrStart +
          (loc.offset / Math.max(0.001, loc.segment.duration)) *
            (loc.segment.narrEnd - loc.segment.narrStart);
        const now = performance.now();
        if (now - lastCommit >= CLOCK_COMMIT_MS) {
          lastCommit = now;
          setVirtual(v);
          setCaptionClock(narr);
        }
      }

      raf = requestAnimationFrame(loop);
    };
    raf = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(raf);
  }, [playing, plan, syncVideos, playTransition, pausePlayback]);

  const toggle = () => {
    if (!hasContent) return;
    if (playing) pausePlayback();
    else beginPlayback(virtualRef.current);
  };

  const timedCaptionWords = React.useMemo(
    () =>
      activeSegment?.words?.filter((w) => !job.removeFillers || !w.filler) ?? [],
    [activeSegment?.words, job.removeFillers],
  );
  const captionWords = React.useMemo(
    () =>
      timedCaptionWords.length > 0
        ? timedCaptionWords.map((w) => w.text)
        : activeSegment
          ? splitWords(activeSegment.overlay || activeSegment.text || "")
          : [],
    [activeSegment, timedCaptionWords],
  );
  const activeWord =
    activeSegment && playing
      ? timedCaptionWords.length > 0
        ? activeTimedWordIndex(
            timedCaptionWords.map((w) => ({ from: w.from, to: w.to })),
            captionClock,
          )
        : activeWordIndex(
            captionWords,
            activeSegment.narrStart,
            activeSegment.narrEnd,
            captionClock,
          )
      : -1;
  const chunkStart = Math.max(
    0,
    Math.floor((activeWord < 0 ? 0 : activeWord) / CAPTION_CHUNK) * CAPTION_CHUNK,
  );
  const chunkWords = captionWords.slice(chunkStart, chunkStart + CAPTION_CHUNK);

  const progressPct =
    plan.totalDuration > 0 ? (virtual / plan.totalDuration) * 100 : 0;

  const showPhoto =
    activeSegment?.lane === "photo" && !activeTransition && activeSegment.posterUrl;
  const showText =
    activeSegment?.lane === "text" && !activeTransition;
  // Distinguish "still rehydrating from IndexedDB" (spinner) from "no local copy
  // exists on this device" (explicit message). undefined = resolving, null = gone.
  const resolvingLocalFootage =
    job.isVideo && localFootageUrl === undefined && activeSegment?.lane === "footage";
  const missingLocalFootage =
    job.isVideo && localFootageUrl === null && activeSegment?.lane === "footage";

  return (
    <div className="flex flex-col gap-3">
      <div
        className={cn(
          "relative w-full overflow-hidden rounded-xl border border-hairline bg-black [container-type:inline-size]",
          ASPECT_STAGE[job.aspect],
        )}
      >
        {/* Layer 0: shared footage element (browser-local blob for uploaded video). */}
        {/* `muted` is controlled imperatively in syncVideos (not as a JSX prop):
            React would otherwise re-assert muted=true on every re-render and
            silence the footage's native-audio fallback. */}
        <video
          ref={footageRef}
          className="absolute inset-0 size-full object-cover transition-opacity duration-75"
          playsInline
          preload="metadata"
          style={{ opacity: 0 }}
        />
        {/* Layer 1: b-roll / animated clip for non-footage beats. */}
        <video
          ref={clipRef}
          className="absolute inset-0 size-full object-cover transition-opacity duration-75"
          playsInline
          preload="metadata"
          style={{ opacity: 0 }}
        />
        {/* Layer 2: photo still */}
        {showPhoto && (
          <img
            src={activeSegment!.posterUrl}
            alt=""
            className="absolute inset-0 size-full object-cover"
          />
        )}
        {/* Layer 3: text card */}
        {showText && (
          <div className="absolute inset-0 grid place-items-center bg-gradient-to-br from-panel-raised to-canvas p-6 text-center">
            <span className="line-clamp-6 max-w-[85%] font-heading text-[clamp(1rem,4.5cqw,1.35rem)] font-semibold text-cream">
              {activeSegment!.overlay || activeSegment!.text}
            </span>
          </div>
        )}
        {/* Layer 4: transition overlay at beat boundaries */}
        <video
          ref={transitionRef}
          className="pointer-events-none absolute inset-0 size-full object-cover mix-blend-screen"
          playsInline
          muted={false}
          preload="metadata"
          style={{ opacity: 0 }}
        />

        {/* Buffering spinner while the footage loads/seeks (slow remote proxy). */}
        {(footageLoading || resolvingLocalFootage) && (
          <div className="pointer-events-none absolute inset-0 grid place-items-center">
            <Loader2 className="size-8 animate-spin text-white/80" />
          </div>
        )}

        {missingLocalFootage && (
          <div className="pointer-events-none absolute inset-0 grid place-items-center bg-black/80 px-6 text-center">
            <div className="max-w-sm space-y-2">
              <p className="font-heading text-sm font-semibold text-cream">
                Local preview file unavailable
              </p>
              <p className="text-xs text-faint">
                This editor preview uses the uploaded file from the current browser
                session. A refresh, dev restart, or opening this project elsewhere
                removes that local file; upload again to restore local preview.
              </p>
            </div>
          </div>
        )}

        <button
          type="button"
          onClick={toggle}
          aria-label={playing ? "Pause preview" : "Play preview"}
          className="group absolute inset-0 grid place-items-center"
          disabled={!hasContent}
        >
          <span
            className={cn(
              "grid size-11 place-items-center rounded-full bg-accent/90 text-accent-foreground shadow-lg backdrop-blur transition-all",
              playing || footageLoading
                ? "opacity-0 group-hover:opacity-100"
                : "opacity-100 hover:scale-105",
              !hasContent && "opacity-40",
            )}
          >
            {playing ? (
              <Pause className="size-5" fill="currentColor" />
            ) : (
              <Play className="size-5 translate-x-0.5" fill="currentColor" />
            )}
          </span>
        </button>

        {job.captions &&
          activeSegment &&
          !activeSegment.suppressCaptions &&
          chunkWords.length > 0 && (
            <div className="pointer-events-none absolute inset-x-0 bottom-[12%] flex flex-wrap items-center justify-center gap-x-1.5 gap-y-0.5 px-4 text-center">
              {chunkWords.map((w, i) => {
                const isActive = chunkStart + i === activeWord;
                return (
                  <span
                    key={`${chunkStart}-${i}-${w}`}
                    className={cn(
                      "inline-block font-heading text-[clamp(0.85rem,4.2cqw,1.35rem)] font-extrabold uppercase leading-none tracking-tight",
                      isActive ? "scale-110 text-accent" : "text-white",
                    )}
                    style={{
                      WebkitTextStroke: "1.5px rgba(0,0,0,0.9)",
                      paintOrder: "stroke fill",
                      textShadow: "0 2px 6px rgba(0,0,0,0.65)",
                    }}
                  >
                    {w}
                  </span>
                );
              })}
            </div>
          )}

        <div className="pointer-events-none absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/70 to-transparent px-3 pb-2 pt-5">
          <div className="h-1 overflow-hidden rounded-full bg-white/20">
            <div
              className="h-full rounded-full bg-accent transition-[width] duration-100"
              style={{ width: `${progressPct}%` }}
            />
          </div>
        </div>
      </div>

      {/* Beat strip — sprite thumbnails; click seeks the shared proxy timeline. */}
      {beats.length > 0 && (
        <div className="flex gap-1.5 overflow-x-auto pb-1 [-ms-overflow-style:none] [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
          {beats.map((beat) => {
            const segIdx = segmentIndexForBeat(plan, beat.index);
            const isActive = segIdx === activeSegIdx && !activeTransition;
            return (
              <SpriteBeatThumb
                key={beat.index}
                beat={beat}
                footageThumbs={job.footageThumbs}
                active={isActive}
                onClick={() => seekToVirtual(plan.segments[segIdx]?.virtualStart ?? 0, true)}
              />
            );
          })}
        </div>
      )}

      <p className="text-center text-[11px] text-faint">
        {hasContent
          ? job.isVideo && footageSrc
            ? "Edit preview · one proxy, seek per beat"
            : "Edit preview · driven from timeline JSON"
          : "Include beats to preview"}
      </p>
    </div>
  );
}
