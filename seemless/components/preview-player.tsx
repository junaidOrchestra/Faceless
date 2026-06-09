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
import { cn } from "@/lib/utils";

export type Scene = {
  kind: "video" | "photo" | "text";
  src?: string;
  poster?: string;
  caption: string;
  startS: number;
  endS: number;
  durationMs: number;
};

export function beatToScene(beat: Beat): Scene {
  // Real-time rough cut: each beat occupies its own narration window.
  const durationMs = Math.max(400, (beat.to - beat.from) * 1000);
  if (beat.visualType === "text_card") {
    return {
      kind: "text",
      caption: beat.overlay || beat.text,
      startS: beat.from,
      endS: beat.to,
      durationMs,
    };
  }
  const asset = findChosenAsset(beat);
  if (asset?.kind === "video" && asset.mediaUrl) {
    return {
      kind: "video",
      src: asset.mediaUrl,
      poster: asset.thumbUrl || undefined,
      caption: beat.text,
      startS: beat.from,
      endS: beat.to,
      durationMs,
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
  return { kind: "text", caption: beat.text, startS: beat.from, endS: beat.to, durationMs };
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
}: {
  job: VideoJob;
  open: boolean;
  onClose: () => void;
}) {
  const scenes = React.useMemo<Scene[]>(() => job.beats.map(beatToScene), [job.beats]);
  const hasContent = scenes.length > 0;
  const canUseAudio = Boolean(job.audioUrl);
  const firstSceneStart = scenes[0]?.startS ?? 0;

  const [playing, setPlaying] = React.useState(false);
  const [idx, setIdx] = React.useState(0);
  const [clock, setClock] = React.useState(firstSceneStart);
  const [audioFailed, setAudioFailed] = React.useState(false);
  const videoRef = React.useRef<HTMLVideoElement>(null);
  const audioRef = React.useRef<HTMLAudioElement>(null);
  const clockRef = React.useRef(firstSceneStart);
  const idxRef = React.useRef(0);
  const lastClockCommitRef = React.useRef(0);
  const useAudio = canUseAudio && !audioFailed;

  React.useEffect(() => {
    idxRef.current = idx;
  }, [idx]);

  const startAudioAt = React.useCallback((startS: number) => {
    const audio = audioRef.current;
    if (!audio) return;
    audio.currentTime = startS;
    void audio.play().catch(() => setAudioFailed(true));
  }, []);

  // Auto-play from the top when the popup opens; stop and reset when it closes.
  React.useEffect(() => {
    if (open && hasContent) {
      idxRef.current = 0;
      clockRef.current = firstSceneStart;
      lastClockCommitRef.current = 0;
      // Defer state reset so React has mounted the media elements before play().
      const t = setTimeout(() => {
        setIdx(0);
        setClock(firstSceneStart);
        setAudioFailed(false);
        setPlaying(true);
        startAudioAt(firstSceneStart);
      }, 0);
      return () => clearTimeout(t);
    }
    audioRef.current?.pause();
    videoRef.current?.pause();
    const t = setTimeout(() => setPlaying(false), 0);
    return () => clearTimeout(t);
  }, [open, hasContent, firstSceneStart, startAudioAt]);

  const sceneIndexForTime = React.useCallback(
    (time: number) => {
      if (scenes.length === 0) return 0;
      if (time < scenes[0].startS) return 0;
      const exact = scenes.findIndex((s) => time >= s.startS && time < s.endS);
      if (exact >= 0) return exact;
      // In a gap between beat windows: hold the most recent scene that has
      // already started rather than snapping to the last clip.
      let held = 0;
      for (let i = 0; i < scenes.length; i++) {
        if (scenes[i].startS <= time) held = i;
        else break;
      }
      return held;
    },
    [scenes],
  );

  // A high-frequency internal clock keeps media/scene switching accurate, but
  // React state is committed at a coarse cadence (and on scene changes). That
  // avoids re-rendering the whole preview subtree at 60fps.
  React.useEffect(() => {
    if (!playing || !hasContent) return;
    let raf = 0;
    const last = scenes[scenes.length - 1];
    const silentStartPerf = performance.now();
    const silentStartClock = clockRef.current;

    const loop = () => {
      const t =
        useAudio && audioRef.current
          ? audioRef.current.currentTime
          : silentStartClock + (performance.now() - silentStartPerf) / 1000;

      clockRef.current = t;

      const ni = sceneIndexForTime(t);
      if (ni !== idxRef.current) {
        idxRef.current = ni;
        setIdx(ni);
        lastClockCommitRef.current = performance.now();
        setClock(t);
      } else {
        const now = performance.now();
        if (now - lastClockCommitRef.current >= REACT_CLOCK_INTERVAL_MS) {
          lastClockCommitRef.current = now;
          setClock(t);
        }
      }

      // The audio element reports its own end via onEnded; drive the silent
      // path's stop here.
      if (!useAudio && t >= last.endS) {
        setPlaying(false);
        idxRef.current = 0;
        setIdx(0);
        clockRef.current = scenes[0].startS;
        lastClockCommitRef.current = 0;
        setClock(scenes[0].startS);
        return;
      }
      raf = requestAnimationFrame(loop);
    };
    raf = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(raf);
  }, [playing, useAudio, hasContent, scenes, sceneIndexForTime]);

  // (Re)start the current video scene whenever it changes during playback.
  React.useEffect(() => {
    if (!playing) return;
    const v = videoRef.current;
    if (v) {
      v.currentTime = 0;
      void v.play().catch(() => {});
    }
  }, [playing, idx]);

  const scene = hasContent ? scenes[Math.min(idx, scenes.length - 1)] : null;
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
      audioRef.current?.pause();
      videoRef.current?.pause();
      setPlaying(false);
      return;
    }
    setPlaying(true);
    if (useAudio) {
      const current = scenes[Math.min(idx, scenes.length - 1)];
      const audio = audioRef.current;
      const withinCurrent =
        audio && current && audio.currentTime >= current.startS && audio.currentTime < current.endS;
      const at = withinCurrent ? audio!.currentTime : current?.startS ?? 0;
      clockRef.current = at;
      startAudioAt(at);
    }
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
              muted
              loop
              playsInline
              preload="metadata"
              className="size-full object-cover"
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
          {job.captions && scene && chunkWords.length > 0 && (
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
            <span>{useAudio ? "with narration" : "no audio"}</span>
          </div>
        </div>

        {job.audioUrl && (
          <audio
            ref={audioRef}
            src={job.audioUrl}
            preload="metadata"
            onEnded={() => {
              setPlaying(false);
              setIdx(0);
              idxRef.current = 0;
              clockRef.current = firstSceneStart;
              setClock(firstSceneStart);
            }}
            onError={() => setAudioFailed(true)}
          />
        )}
      </DialogContent>
    </Dialog>
  );
}
