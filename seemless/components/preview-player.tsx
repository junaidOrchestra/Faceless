"use client";

import * as React from "react";
import { Pause, Play } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogTitle,
} from "@/components/ui/dialog";
import { LogoMark } from "@/components/brand";
import type { Aspect, Beat, VideoJob } from "@/lib/types";
import { findChosenAsset } from "@/lib/store";
import {
  decodeNarration,
  getCachedNarration,
  getSharedAudioCtx,
} from "@/lib/preview-audio";
import { cn } from "@/lib/utils";

export type Scene = {
  kind: "video" | "photo" | "text";
  src?: string;
  poster?: string;
  caption: string;
  startS: number;
  endS: number;
  durationMs: number;
  sourceInS?: number;
  // True when this clip carries its OWN audio that should be heard (an animated
  // text card's per-word SFX). Such clips play unmuted so the sound is audible
  // alongside the Web-Audio narration; all other clips stay muted.
  hasOwnAudio?: boolean;
  // Standalone inserted text cards have no narration window. The preview should
  // leave a silent gap in the narration while their own SFX/video plays.
  skipNarration?: boolean;
  suppressCaptions?: boolean;
};

export function beatToScene(beat: Beat): Scene {
  const asset = findChosenAsset(beat);
  const isInsert = (beat.kind ?? "narration") === "insert";
  const startS = isInsert ? 0 : beat.from;
  const endS = isInsert ? Math.max(0.2, beat.durationS ?? beat.to - beat.from) : beat.to;
  // Real-time rough cut: narration beats occupy their source narration window;
  // inserted cards occupy their own local duration and skip narration.
  const durationMs = Math.max(400, (endS - startS) * 1000);
  if (asset?.kind === "video" && asset.mediaUrl) {
    return {
      kind: "video",
      src: asset.mediaUrl,
      poster: asset.thumbUrl || undefined,
      caption: beat.text,
      startS,
      endS,
      durationMs,
      sourceInS: asset.sourceInS,
      hasOwnAudio: asset.source === "animated",
      skipNarration: isInsert,
      suppressCaptions: asset.source === "animated",
    };
  }
  if (beat.visualType === "text_card") {
    return {
      kind: "text",
      caption: beat.overlay || beat.text,
      startS,
      endS,
      durationMs,
      skipNarration: isInsert,
      suppressCaptions: isInsert,
    };
  }
  if (asset) {
    return {
      kind: "photo",
      poster: asset.thumbUrl || undefined,
      caption: beat.text,
      startS: beat.from,
      endS: beat.to,
      durationMs,
    };
  }
  return { kind: "text", caption: beat.text, startS, endS, durationMs };
}

// Modal width per aspect; the stage's aspect-ratio sets the height.
const ASPECT_MODAL: Record<Aspect, string> = {
  "9:16": "w-[min(92vw,380px)]",
  "16:9": "w-[min(92vw,880px)]",
  "1:1": "w-[min(92vw,560px)]",
};

const ASPECT_STAGE: Record<Aspect, string> = {
  "9:16": "aspect-[9/16]",
  "16:9": "aspect-video",
  "1:1": "aspect-square",
};

// How many words to show on screen at once (Hormozi-style punchy chunks).
const CAPTION_CHUNK = 4;
const REACT_CLOCK_INTERVAL_MS = 80;

function splitWords(text: string): string[] {
  return text.trim().split(/\s+/).filter(Boolean);
}

/**
 * Index of the word being spoken at `clock`, within a beat's [startS, endS]
 * window. The orchestrator only gives per-beat timing, so we distribute words
 * across the window weighted by length (longer words ~ more time) — an
 * approximation that tracks the narration closely enough for a karaoke effect.
 */
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

/**
 * Full-size, centered rough-cut player. Plays each beat's chosen clip for its
 * narration window; if narration audio is available it drives the timeline,
 * otherwise a timer does. No backend encode — this is a browser-side preview.
 */
export function PreviewPlayer({
  job,
  open,
  onClose,
  beatIndex = null,
}: {
  job: VideoJob;
  open: boolean;
  onClose: () => void;
  /**
   * When set, preview just this single beat (by index) instead of the whole
   * rough cut — used by the per-row "play this beat" button. The beat is shown
   * regardless of whether it's included, so users can audition any beat.
   */
  beatIndex?: number | null;
}) {
  // Single-beat mode shows exactly that beat; otherwise only the beats the user
  // kept (ticked) appear, matching the final render (excluded beats are dropped).
  const scenes = React.useMemo<Scene[]>(() => {
    if (beatIndex !== null) {
      const b = job.beats.find((x) => x.index === beatIndex);
      return b ? [beatToScene(b)] : [];
    }
    return job.beats.filter((b) => b.included).map(beatToScene);
  }, [job.beats, beatIndex]);
  const hasContent = scenes.length > 0;
  const canUseAudio = Boolean(job.audioUrl);
  const firstSceneStart = scenes[0]?.startS ?? 0;
  const hasNarrationGaps = scenes.some((s) => s.skipNarration);

  const [playing, setPlaying] = React.useState(false);
  const [idx, setIdx] = React.useState(0);
  const [clock, setClock] = React.useState(firstSceneStart);
  // Two independent failure flags: if Web Audio can't decode/play the source we
  // fall back to a plain <audio> element so there's still sound.
  const [webAudioFailed, setWebAudioFailed] = React.useState(false);
  const [elementFailed, setElementFailed] = React.useState(false);
  const [audioReady, setAudioReady] = React.useState(false);
  const videoRef = React.useRef<HTMLVideoElement>(null);
  const audioRef = React.useRef<HTMLAudioElement>(null);
  const idxRef = React.useRef(0);
  const lastClockCommitRef = React.useRef(0);

  // Audio engine selection. Preferred path is Web Audio: we decode the narration
  // once and play only the KEPT windows by scheduling buffer slices. This is
  // SEEK-INDEPENDENT and guarantees excluded beats' audio is never heard and the
  // kept beats play back-to-back, matching the render. If decoding fails (e.g. a
  // streaming/range proxy an <audio> element tolerates but decodeAudioData
  // can't), we fall back to an <audio> element that at least plays sound.
  const useWebAudio = canUseAudio && audioReady && !webAudioFailed;
  const useElement = canUseAudio && webAudioFailed && !elementFailed && !hasNarrationGaps;
  const hasNarration = useWebAudio || useElement;
  // Decode has resolved one way or the other (or there's no audio to wait for).
  const decodeSettled = !canUseAudio || audioReady || webAudioFailed;

  const audioCtxRef = React.useRef<AudioContext | null>(null);
  const bufferRef = React.useRef<AudioBuffer | null>(null);
  const sourcesRef = React.useRef<AudioBufferSourceNode[]>([]);
  const anchorRef = React.useRef<
    { virtual: number; mode: "audio"; ctxTime: number } | { virtual: number; mode: "silent"; perf: number } | null
  >(null);
  const pausedVirtualRef = React.useRef(0);

  React.useEffect(() => {
    idxRef.current = idx;
  }, [idx]);

  // Contiguous virtual timeline: each kept scene occupies [offset, offset+dur).
  const segs = React.useMemo(() => {
    return scenes.reduce<{ scene: Scene; offset: number; dur: number }[]>((out, s) => {
      const offset = out.length ? out[out.length - 1].offset + out[out.length - 1].dur : 0;
      const dur = Math.max(0.05, s.endS - s.startS);
      out.push({ scene: s, offset, dur });
      return out;
    }, []);
  }, [scenes]);
  const totalDur = segs.length ? segs[segs.length - 1].offset + segs[segs.length - 1].dur : 0;

  const idxForVirtual = React.useCallback(
    (v: number) => {
      for (let i = segs.length - 1; i >= 0; i--) {
        if (v >= segs[i].offset - 1e-6) return i;
      }
      return 0;
    },
    [segs],
  );

  const stopAllSources = React.useCallback(() => {
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

  // Schedule every kept window from virtual position `vpos` onward, so they play
  // gaplessly. Returns false if the buffer isn't ready (caller falls back).
  const scheduleAudioFrom = React.useCallback(
    (vpos: number): boolean => {
      const ctx = audioCtxRef.current;
      const buffer = bufferRef.current;
      if (!ctx || !buffer) return false;
      stopAllSources();
      const ctxAnchor = ctx.currentTime + 0.04; // small lead so the first slice isn't clipped
      anchorRef.current = { virtual: vpos, mode: "audio", ctxTime: ctxAnchor };
      for (const seg of segs) {
        const segEnd = seg.offset + seg.dur;
        if (segEnd <= vpos + 1e-3) continue;
        const segVirtualStart = Math.max(seg.offset, vpos);
        const within = segVirtualStart - seg.offset;
        const when = ctxAnchor + (segVirtualStart - vpos);
        if (seg.scene.skipNarration) continue;
        const srcOffset = seg.scene.startS + within;
        const dur = seg.dur - within;
        const src = ctx.createBufferSource();
        src.buffer = buffer;
        src.connect(ctx.destination);
        try {
          src.start(when, srcOffset, dur);
        } catch {
          // start can throw if args are out of range; skip this slice
        }
        sourcesRef.current.push(src);
      }
      return true;
    },
    [segs, stopAllSources],
  );

  const stopAndReset = React.useCallback(() => {
    stopAllSources();
    audioRef.current?.pause();
    setPlaying(false);
    idxRef.current = 0;
    pausedVirtualRef.current = 0;
    anchorRef.current = null;
    setIdx(0);
    lastClockCommitRef.current = 0;
    setClock(scenes[0]?.startS ?? 0);
  }, [scenes, stopAllSources]);

  const beginPlayback = React.useCallback(
    (vpos: number) => {
      if (useWebAudio && audioCtxRef.current && bufferRef.current) {
        scheduleAudioFrom(vpos);
        // Resume after scheduling (sticky user activation from opening the
        // player allows this); slices are scheduled relative to the context
        // clock, so they fire correctly once it's running.
        void audioCtxRef.current.resume().catch(() => {});
      } else if (useElement && audioRef.current) {
        // Degraded fallback: seek the element near the first kept beat (best
        // effort — ignored if the source isn't seekable) and play. The
        // element-mode loop handles per-scene skipping from here.
        const el = audioRef.current;
        const startScene = scenes[idxForVirtual(vpos)] ?? scenes[0];
        try {
          el.currentTime = startScene?.startS ?? 0;
        } catch {
          // not seekable yet; the element loop retries
        }
        void el.play().catch(() => setElementFailed(true));
        anchorRef.current = null;
      } else {
        // Silent rough cut (no narration available / both engines failed): a
        // perf timer walks the same contiguous timeline.
        anchorRef.current = { virtual: vpos, mode: "silent", perf: performance.now() };
      }
      setPlaying(true);
    },
    [useWebAudio, useElement, scheduleAudioFrom, scenes, idxForVirtual],
  );

  // Point at the shared context and use the decoded buffer (instant if prewarm
  // or a prior open already cached it). The context/buffer persist across opens.
  React.useEffect(() => {
    if (!open || !canUseAudio || !job.audioUrl) return;
    let cancelled = false;
    const ctx = getSharedAudioCtx();
    audioCtxRef.current = ctx;
    if (!ctx) {
      setWebAudioFailed(true);
      return;
    }
    // Browsers start the context "suspended" until a user gesture; resume now
    // (opening the player is a gesture) and again on the next interaction so
    // audio isn't silently blocked by the autoplay policy.
    const resumeOnGesture = () => {
      void ctx.resume().catch(() => {});
    };
    void ctx.resume().catch(() => {});
    window.addEventListener("pointerdown", resumeOnGesture);
    window.addEventListener("keydown", resumeOnGesture);

    const url = job.audioUrl;
    const cached = getCachedNarration(url);
    if (cached) {
      // Instant path: reuse the buffer decoded by prewarm or a previous open.
      bufferRef.current = cached;
      setAudioReady(true);
    } else {
      setAudioReady(false);
      decodeNarration(url)
        .then((decoded) => {
          if (cancelled) return;
          bufferRef.current = decoded;
          setAudioReady(true);
        })
        .catch(() => {
          // Source isn't decodable here — fall back to an <audio> element.
          if (!cancelled) setWebAudioFailed(true);
        });
    }
    return () => {
      cancelled = true;
      window.removeEventListener("pointerdown", resumeOnGesture);
      window.removeEventListener("keydown", resumeOnGesture);
      stopAllSources();
      // Keep the shared context and cached buffer alive for instant reopen.
    };
  }, [open, canUseAudio, job.audioUrl, stopAllSources]);

  // Auto-play from the first kept beat once content (and audio, if any) is ready.
  const startedRef = React.useRef(false);
  React.useEffect(() => {
    if (!open) {
      startedRef.current = false;
      stopAllSources();
      audioRef.current?.pause();
      videoRef.current?.pause();
      setPlaying(false);
      setIdx(0);
      idxRef.current = 0;
      return;
    }
    if (!hasContent || startedRef.current) return;
    // Wait for the decode attempt to resolve so we pick the right engine.
    if (!decodeSettled) return;
    startedRef.current = true;
    setIdx(0);
    idxRef.current = 0;
    setClock(scenes[0]?.startS ?? 0);
    beginPlayback(0);
  }, [open, hasContent, decodeSettled, scenes, beginPlayback, stopAllSources]);

  // Drive scene switching + caption clock from the contiguous virtual timeline
  // (Web Audio context clock when playing with sound, else a perf timer). Not
  // used in element-fallback mode, which walks the original timeline instead.
  React.useEffect(() => {
    if (!playing || !hasContent || useElement) return;
    let raf = 0;
    const loop = () => {
      const a = anchorRef.current;
      if (!a) {
        raf = requestAnimationFrame(loop);
        return;
      }
      const v =
        a.mode === "audio" && audioCtxRef.current
          ? a.virtual + (audioCtxRef.current.currentTime - a.ctxTime)
          : a.mode === "silent"
            ? a.virtual + (performance.now() - a.perf) / 1000
            : a.virtual;

      if (v >= totalDur - 0.02) {
        stopAndReset();
        return;
      }
      const i = idxForVirtual(v);
      if (i !== idxRef.current) {
        idxRef.current = i;
        setIdx(i);
        lastClockCommitRef.current = performance.now();
      }
      const seg = segs[i];
      const sceneClock = seg ? seg.scene.startS + (v - seg.offset) : 0;
      const now = performance.now();
      if (now - lastClockCommitRef.current >= REACT_CLOCK_INTERVAL_MS) {
        lastClockCommitRef.current = now;
        setClock(sceneClock);
      }
      raf = requestAnimationFrame(loop);
    };
    raf = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(raf);
  }, [playing, hasContent, useElement, segs, totalDur, idxForVirtual, stopAndReset]);

  // Element-fallback loop: the <audio> element plays the whole file along the
  // ORIGINAL timeline, so we advance scene-by-scene and seek across the excluded
  // gaps (best effort). Used only when Web Audio decoding failed.
  React.useEffect(() => {
    if (!playing || !hasContent || !useElement) return;
    let raf = 0;
    let curIdx = idxRef.current;
    let reseekAttempts = 0;

    const enterScene = (i: number) => {
      curIdx = i;
      idxRef.current = i;
      reseekAttempts = 0;
      setIdx(i);
      const s = scenes[i];
      const el = audioRef.current;
      if (el && Math.abs(el.currentTime - s.startS) > 0.05) {
        try {
          el.currentTime = s.startS;
        } catch {
          // not seekable; loop retries below
        }
      }
      lastClockCommitRef.current = performance.now();
      setClock(s.startS);
    };

    const loop = () => {
      const el = audioRef.current;
      const s = scenes[curIdx];
      if (!el || !s) {
        stopAndReset();
        return;
      }
      const t = el.currentTime;
      // Re-assert the seek if the element is still before this kept window.
      if (t < s.startS - 0.05 && reseekAttempts < 60) {
        reseekAttempts += 1;
        try {
          el.currentTime = s.startS;
        } catch {
          // ignore
        }
        raf = requestAnimationFrame(loop);
        return;
      }
      if (t >= s.endS - 0.02) {
        if (curIdx + 1 < scenes.length) {
          enterScene(curIdx + 1);
        } else {
          stopAndReset();
          return;
        }
      } else {
        const now = performance.now();
        if (now - lastClockCommitRef.current >= REACT_CLOCK_INTERVAL_MS) {
          lastClockCommitRef.current = now;
          setClock(t);
        }
      }
      raf = requestAnimationFrame(loop);
    };
    raf = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(raf);
  }, [playing, hasContent, useElement, scenes, stopAndReset]);

  const scene = hasContent ? scenes[Math.min(idx, scenes.length - 1)] : null;

  // Keep the on-screen <video> in lockstep with playback state: (re)start it
  // from the scene's in-point when playing (and on each scene change), and pause
  // it whenever the rough cut is paused. Driving it from `playing` — rather than
  // pausing imperatively in the toggle — guarantees the video can never keep
  // running after audio stops, regardless of which code path paused us.
  React.useEffect(() => {
    const v = videoRef.current;
    if (!v) return;
    if (playing) {
      v.currentTime = scene?.sourceInS ?? 0;
      void v.play().catch(() => {});
    } else {
      v.pause();
    }
  }, [playing, idx, scene?.sourceInS]);

  const sceneProgress =
    scene && playing
      ? Math.max(0, Math.min(100, ((clock - scene.startS) / Math.max(0.001, scene.endS - scene.startS)) * 100))
      : 0;

  // Hormozi-style caption: a short window of words with the spoken one in accent.
  const captionWords = React.useMemo(() => (scene ? splitWords(scene.caption) : []), [scene]);
  const activeWord =
    scene && playing ? activeWordIndex(captionWords, scene.startS, scene.endS, clock) : -1;
  const chunkStart = Math.max(0, Math.floor((activeWord < 0 ? 0 : activeWord) / CAPTION_CHUNK) * CAPTION_CHUNK);
  const chunkWords = captionWords.slice(chunkStart, chunkStart + CAPTION_CHUNK);

  const toggle = () => {
    if (!hasContent) return;
    if (playing) {
      if (useElement) {
        // Element keeps its own position; just pause in place.
        audioRef.current?.pause();
      } else {
        // Remember the virtual position so resume picks up where we left off.
        const a = anchorRef.current;
        if (a) {
          pausedVirtualRef.current =
            a.mode === "audio" && audioCtxRef.current
              ? a.virtual + (audioCtxRef.current.currentTime - a.ctxTime)
              : a.mode === "silent"
                ? a.virtual + (performance.now() - a.perf) / 1000
                : a.virtual;
        }
        stopAllSources();
      }
      videoRef.current?.pause();
      setPlaying(false);
      return;
    }
    if (useElement) {
      // Resume in place — don't reseek to a scene start.
      void audioRef.current?.play().catch(() => setElementFailed(true));
      void audioCtxRef.current?.resume().catch(() => {});
      setPlaying(true);
      return;
    }
    const resumeAt = pausedVirtualRef.current < totalDur - 0.05 ? pausedVirtualRef.current : 0;
    beginPlayback(resumeAt);
  };

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent
        hideClose
        className={cn("border-hairline bg-black p-0", ASPECT_MODAL[job.aspect])}
      >
        <DialogTitle className="sr-only">Preview your video</DialogTitle>

        <div className={cn("relative w-full overflow-hidden rounded-2xl bg-black [container-type:inline-size]", ASPECT_STAGE[job.aspect])}>
          {/* Stage */}
          {scene?.kind === "video" ? (
            <video
              ref={videoRef}
              key={`v-${idx}`}
              src={scene.src}
              poster={scene.poster}
              muted={!scene.hasOwnAudio}
              loop={scene.sourceInS === undefined}
              playsInline
              preload="metadata"
              className="size-full object-cover"
              onLoadedMetadata={(e) => {
                // React's `muted` attribute is unreliable; enforce on the element.
                e.currentTarget.muted = !scene.hasOwnAudio;
                e.currentTarget.currentTime = scene.sourceInS ?? 0;
              }}
            />
          ) : scene?.kind === "photo" ? (
            <img src={scene.poster} alt="" className="size-full object-cover" />
          ) : (
            <div className="grid size-full place-items-center bg-gradient-to-br from-panel-raised to-canvas p-6 text-center">
              <span className="line-clamp-6 max-w-[80%] font-heading text-lg font-semibold text-cream">
                {scene?.caption}
              </span>
            </div>
          )}

          {/* Brand watermark */}
          <div className="pointer-events-none absolute right-2.5 top-6 z-10 flex items-center gap-1.5 rounded-full bg-black/35 px-2 py-1 backdrop-blur-sm">
            <LogoMark className="size-4 rounded-[5px]" />
            <span className="font-heading text-[11px] font-bold leading-none tracking-tight text-white drop-shadow">
              Broll<span className="text-accent">io</span>
            </span>
          </div>

          {/* Click anywhere to toggle play/pause */}
          <button
            type="button"
            onClick={toggle}
            aria-label={playing ? "Pause" : "Play"}
            className="group absolute inset-0 grid place-items-center"
          >
            <span
              className={cn(
                "grid size-16 place-items-center rounded-full bg-accent/90 text-accent-foreground shadow-xl backdrop-blur transition-all",
                playing ? "opacity-0 group-hover:opacity-100" : "opacity-100 hover:scale-105",
              )}
            >
              {playing ? (
                <Pause className="size-7" fill="currentColor" />
              ) : (
                <Play className="size-7 translate-x-0.5" fill="currentColor" />
              )}
            </span>
          </button>

          {/* Hormozi-style word-by-word captions */}
          {job.captions && scene && !scene.suppressCaptions && chunkWords.length > 0 && (
            <div className="pointer-events-none absolute inset-x-0 bottom-[14%] flex flex-wrap items-center justify-center gap-x-2 gap-y-1 px-5 text-center">
              {chunkWords.map((w, i) => {
                const isActive = chunkStart + i === activeWord;
                return (
                  <span
                    key={`${chunkStart}-${i}-${w}`}
                    className={cn(
                      "inline-block font-heading text-[clamp(1.1rem,5cqw,2rem)] font-extrabold uppercase leading-none tracking-tight transition-transform duration-100",
                      isActive ? "scale-110 text-accent" : "text-white",
                    )}
                    style={{
                      WebkitTextStroke: "2px rgba(0,0,0,0.9)",
                      paintOrder: "stroke fill",
                      textShadow: "0 2px 8px rgba(0,0,0,0.65)",
                    }}
                  >
                    {w}
                  </span>
                );
              })}
            </div>
          )}

          {/* Per-scene progress segments */}
          {hasContent && (
            <div className="absolute inset-x-3 top-3 flex gap-1">
              {scenes.map((_, i) => (
                <span key={i} className="h-1 flex-1 overflow-hidden rounded-full bg-white/25">
                  <span
                    className={cn(
                      "block h-full rounded-full bg-white",
                      i < idx ? "w-full" : i === idx && playing ? "" : "w-0",
                    )}
                    style={
                      i === idx && playing
                        ? {
                            width: `${sceneProgress}%`,
                            transitionProperty: "width",
                            transitionTimingFunction: "linear",
                            transitionDuration: "90ms",
                          }
                        : undefined
                    }
                  />
                </span>
              ))}
            </div>
          )}

          {/* Footer meta */}
          <div className="pointer-events-none absolute inset-x-0 bottom-0 flex items-center justify-between bg-gradient-to-t from-black/70 to-transparent px-3 pb-2 pt-6 text-[11px] text-white/80">
            <span className="font-mono">
              {scene ? `${idx + 1} / ${scenes.length}` : ""}
            </span>
            <span>
              {scene?.skipNarration
                ? scene.hasOwnAudio
                  ? "SFX only"
                  : "silent card"
                : hasNarration
                  ? "with narration"
                : canUseAudio && !decodeSettled
                  ? "loading audio…"
                  : "no audio"}
            </span>
          </div>
        </div>

        {/* Fallback narration source, mounted only when Web Audio decoding
            failed. The element-mode loop drives skipping by seeking it. */}
        {job.audioUrl && webAudioFailed && (
          <audio
            ref={audioRef}
            src={job.audioUrl}
            preload="auto"
            onEnded={stopAndReset}
            onError={() => setElementFailed(true)}
          />
        )}
      </DialogContent>
    </Dialog>
  );
}
