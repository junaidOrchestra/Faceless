"use client";

import * as React from "react";
import { Loader2, Replace, Type, Video } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Button } from "@/components/ui/button";
import type { Beat } from "@/lib/types";
import { VISUAL_TYPE_LABEL } from "@/lib/types";
import { findChosenAsset } from "@/lib/store";
import { cn, fmtRange } from "@/lib/utils";

function SourcePill({ source }: { source: string }) {
  return (
    <span className="absolute bottom-1 left-1 rounded bg-black/70 px-1.5 py-0.5 text-[9px] font-medium uppercase tracking-wide text-white/90 backdrop-blur">
      {source === "yours" ? "yours" : source}
    </span>
  );
}

function Thumb({ beat, searching }: { beat: Beat; searching?: boolean }) {
  const videoRef = React.useRef<HTMLVideoElement>(null);
  const [active, setActive] = React.useState(false);

  if (beat.loading) {
    return (
      <div className="relative size-full">
        <Skeleton className="size-full rounded-lg" />
        {searching && (
          <span className="absolute inset-0 grid place-items-center">
            <Loader2 className="size-4 animate-spin text-accent/80" />
          </span>
        )}
      </div>
    );
  }

  if (beat.visualType === "text_card") {
    return (
      <div className="flex size-full flex-col items-center justify-center gap-1 rounded-lg border border-hairline bg-gradient-to-br from-panel-raised to-canvas p-2 text-center">
        <Type className="size-3.5 text-accent" />
        <span className="line-clamp-3 text-[10px] font-medium leading-tight text-cream">
          {beat.overlay || "Add caption"}
        </span>
      </div>
    );
  }

  const asset = findChosenAsset(beat);
  if (!asset) {
    return (
      <div className="grid size-full place-items-center rounded-lg border border-dashed border-hairline bg-panel-raised text-faint">
        <span className="text-[10px]">No clip</span>
      </div>
    );
  }

  // Keep the list cheap: show the poster image by default and mount a <video>
  // only while the row is hovered/focused. This avoids 40-70 metadata loads for
  // long scripts while preserving hover-preview behavior.
  const isVideo = asset.kind === "video" && Boolean(asset.mediaUrl);
  const poster = asset.thumbUrl || undefined;
  const videoSrc = poster ? asset.mediaUrl : `${asset.mediaUrl}#t=0.1`;

  const play = () => {
    if (!isVideo) return;
    setActive(true);
  };
  const stop = () => {
    const v = videoRef.current;
    if (v) {
      v.pause();
      v.currentTime = 0;
    }
    setActive(false);
  };

  return (
    <div
      className="relative size-full overflow-hidden rounded-lg border border-hairline bg-canvas"
      onMouseEnter={isVideo ? play : undefined}
      onMouseLeave={isVideo ? stop : undefined}
      onFocus={isVideo ? play : undefined}
      onBlur={isVideo ? stop : undefined}
    >
      {isVideo && active ? (
        <video
          ref={videoRef}
          src={videoSrc}
          poster={poster}
          autoPlay
          muted
          loop
          playsInline
          preload="metadata"
          className="size-full object-cover"
        />
      ) : poster ? (
        <img
          src={poster}
          alt=""
          className="size-full object-cover"
          loading="lazy"
        />
      ) : isVideo ? (
        <div className="grid size-full place-items-center text-faint">
          <Video className="size-5" />
        </div>
      ) : (
        <img
          src={asset.thumbUrl}
          alt=""
          className="size-full object-cover"
          loading="lazy"
        />
      )}
      {asset.kind === "video" && (
        <span className="absolute right-1 top-1 grid size-4 place-items-center rounded bg-black/60 text-white">
          <Video className="size-2.5" />
        </span>
      )}
      <SourcePill source={asset.source} />
    </div>
  );
}

export const BeatRow = React.memo(function BeatRow({
  beat,
  index,
  searching,
  locked = false,
  onOpenPicker,
}: {
  beat: Beat;
  index: number;
  searching?: boolean;
  locked?: boolean;
  onOpenPicker: (beatIndex: number) => void;
}) {
  const needsChoice =
    !locked &&
    (beat.visualType === "text_card"
      ? !(beat.overlay && beat.overlay.trim())
      : !beat.chosenAssetId && !beat.loading);

  const interactive = !beat.loading && !locked;

  return (
    <li
      role={interactive ? "button" : undefined}
      tabIndex={interactive ? 0 : undefined}
      onClick={interactive ? () => onOpenPicker(index) : undefined}
      onKeyDown={
        interactive
          ? (e) => {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                onOpenPicker(index);
              }
            }
          : undefined
      }
      aria-label={interactive ? "Change clip" : undefined}
      className={cn(
        "group panel flex animate-fade-rise items-start gap-4 p-3 transition-colors hover:border-hairline/90 sm:p-4",
        interactive &&
          "cursor-pointer hover:border-accent/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/60",
      )}
      style={{ animationDelay: `${Math.min(index * 35, 500)}ms` }}
    >
      <div className="relative size-20 shrink-0 sm:size-24">
        <Thumb beat={beat} searching={searching} />
        {needsChoice && (
          <span className="absolute -right-1 -top-1 size-2.5 rounded-full bg-accent ring-2 ring-canvas" />
        )}
      </div>

      <div className="min-w-0 flex-1">
        <div className="mb-1.5 flex flex-wrap items-center gap-2">
          <Badge variant={beat.visualType === "text_card" ? "accent" : "default"}>
            {VISUAL_TYPE_LABEL[beat.visualType]}
          </Badge>
          <span className="font-mono text-[11px] text-faint">
            {fmtRange(beat.from, beat.to)}
          </span>
          {beat.loading && searching && (
            <span className="flex items-center gap-1 text-[11px] font-medium text-accent">
              <Loader2 className="size-3 animate-spin" />
              finding clip…
            </span>
          )}
        </div>
        <p
          className={cn(
            "text-sm leading-relaxed text-cream/90",
            beat.loading && "text-faint",
          )}
        >
          {beat.text}
        </p>
      </div>

      {!locked && (
        <Button
          size="icon-sm"
          variant="ghost"
          className="shrink-0 opacity-60 transition-opacity group-hover:opacity-100"
          onClick={(e) => {
            e.stopPropagation();
            onOpenPicker(index);
          }}
          disabled={beat.loading}
          aria-label="Change clip"
          title="Change clip"
        >
          <Replace className="size-4" />
        </Button>
      )}
    </li>
  );
});
