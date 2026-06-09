"use client";

import * as React from "react";
import { Pause, Play } from "lucide-react";
import { Button } from "@/components/ui/button";
import { fmtTime } from "@/lib/utils";

export function AudioPlayer({
  fileName,
  duration,
  audioUrl,
}: {
  fileName: string;
  duration: number;
  audioUrl?: string;
}) {
  const mediaRef = React.useRef<HTMLAudioElement | HTMLVideoElement>(null);
  const [playing, setPlaying] = React.useState(false);
  const [pos, setPos] = React.useState(0);
  const isVideoSource = /\.(mp4|webm|mov|mkv|ogv|mpg|mpeg)$/i.test(fileName);

  React.useEffect(() => {
    setPlaying(false);
    setPos(0);
  }, [audioUrl]);

  const toggle = () => {
    const media = mediaRef.current;
    if (!media) return;
    if (playing) {
      media.pause();
      return;
    }
    if (duration > 0 && media.currentTime >= duration) {
      media.currentTime = 0;
    }
    void media.play().catch(() => setPlaying(false));
  };

  const pct = duration > 0 ? Math.min(100, (pos / duration) * 100) : 0;
  const mediaProps = {
    ref: mediaRef as React.Ref<HTMLAudioElement & HTMLVideoElement>,
    src: audioUrl,
    preload: "metadata",
    onPlay: () => setPlaying(true),
    onPause: () => setPlaying(false),
    onEnded: () => {
      setPlaying(false);
      setPos(duration);
    },
    onTimeUpdate: (e: React.SyntheticEvent<HTMLMediaElement>) => {
      setPos(e.currentTarget.currentTime);
    },
    className: "hidden",
  };

  return (
    <div className="flex min-w-0 items-center gap-3">
      {audioUrl ? (
        isVideoSource ? (
          <video {...mediaProps} playsInline />
        ) : (
          <audio {...mediaProps} />
        )
      ) : null}
      <Button
        size="icon-sm"
        variant="secondary"
        onClick={toggle}
        disabled={!audioUrl}
        aria-label={playing ? "Pause" : "Play"}
      >
        {playing ? <Pause className="size-3.5" /> : <Play className="size-3.5" />}
      </Button>
      <div className="min-w-0">
        <p className="truncate text-sm font-medium text-cream" title={fileName}>
          {fileName}
        </p>
        <div className="flex items-center gap-2">
          <span className="font-mono text-[11px] text-faint">{fmtTime(pos)}</span>
          <div className="relative h-1 w-28 overflow-hidden rounded-full bg-panel-raised sm:w-40">
            <div
              className="absolute inset-y-0 left-0 rounded-full bg-accent transition-[width] duration-200"
              style={{ width: `${pct}%` }}
            />
          </div>
          <span className="font-mono text-[11px] text-faint">{fmtTime(duration)}</span>
        </div>
        {!audioUrl && (
          <p className="text-[10px] text-faint/70">
            Audio preview is available only in the current upload session.
          </p>
        )}
      </div>
    </div>
  );
}
