"use client";

import * as React from "react";
import { Check, Loader2, Pencil, Play, Plus, Replace, Type, Video, X } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
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

function Thumb({
  beat,
  searching,
  footageUrl,
}: {
  beat: Beat;
  searching?: boolean;
  /** Local object URL of the uploaded video, used for "your footage" beats. */
  footageUrl?: string | null;
}) {
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
  // The whole-video upload plays from the local file (instant, no cloud fetch)
  // when we have it; everything else (incl. per-beat library uploads) uses the
  // canonical cloud media_url. sourceInS marks the main footage (see preview).
  const isMainFootage = asset.source === "yours" && asset.sourceInS !== undefined;
  const baseMediaUrl = isMainFootage && footageUrl ? footageUrl : asset.mediaUrl;
  const isVideo = asset.kind === "video" && Boolean(baseMediaUrl);
  const poster = asset.thumbUrl || undefined;
  const sourceInS = asset.sourceInS ?? 0;
  const videoSrc = poster ? baseMediaUrl : `${baseMediaUrl}#t=${Math.max(0.1, sourceInS)}`;

  const play = () => {
    if (!isVideo) return;
    setActive(true);
  };
  const stop = () => {
    const v = videoRef.current;
    if (v) {
      v.pause();
      v.currentTime = sourceInS;
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
          onLoadedMetadata={(e) => {
            e.currentTarget.currentTime = sourceInS;
          }}
        />
      ) : poster ? (
        <img
          src={poster}
          alt=""
          className="size-full object-cover"
          loading="lazy"
        />
      ) : isVideo ? (
        <video
          src={videoSrc}
          muted
          playsInline
          preload="metadata"
          className="size-full object-cover"
          onLoadedMetadata={(e) => {
            e.currentTarget.currentTime = sourceInS;
          }}
        />
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
  strikeFillers = false,
  footageUrl,
  onOpenPicker,
  onToggleIncluded,
  onPlayBeat,
  onEditText,
}: {
  beat: Beat;
  index: number;
  searching?: boolean;
  locked?: boolean;
  /** When true, filler words ("um"/"uh"/…) are struck through in the text. */
  strikeFillers?: boolean;
  /** Local object URL of the uploaded video (for "your footage" thumbnails). */
  footageUrl?: string | null;
  onOpenPicker: (beatIndex: number) => void;
  onToggleIncluded?: (beatIndex: number) => void;
  /** Preview just this beat (opens the rough-cut player scoped to it). */
  onPlayBeat?: (beatIndex: number) => void;
  /** Correct a mis-transcribed word. Returns a promise while it persists (and,
   *  for animated cards, re-records the clip with the corrected text). */
  onEditText?: (beatIndex: number, text: string) => void | Promise<void>;
}) {
  const [editing, setEditing] = React.useState(false);
  const [saving, setSaving] = React.useState(false);
  const [draft, setDraft] = React.useState(beat.text);

  // Render word-by-word only when we're striking fillers and there is at least
  // one to strike; otherwise keep the plain (cheaper) text.
  const fillerWords = beat.words?.filter((w) => w.filler) ?? [];
  const showWords = strikeFillers && fillerWords.length > 0 && beat.included;
  // A text fix re-records animated cards (the text is baked into the clip), so a
  // save can take a few seconds for those beats.
  const chosenAsset = findChosenAsset(beat);
  const isAnimated = chosenAsset?.source === "animated";
  const canEditText = Boolean(onEditText) && !locked && !beat.loading;

  const startEdit = () => {
    setDraft(beat.text);
    setEditing(true);
  };
  const cancelEdit = () => {
    if (saving) return;
    setEditing(false);
  };
  const saveEdit = async () => {
    const next = draft.trim();
    if (!next || next === beat.text) {
      setEditing(false);
      return;
    }
    setSaving(true);
    try {
      await onEditText?.(index, next);
    } finally {
      setSaving(false);
      setEditing(false);
    }
  };
  const needsChoice =
    beat.included &&
    !locked &&
    (beat.visualType === "text_card"
      ? !(beat.overlay && beat.overlay.trim())
      : !beat.chosenAssetId && !beat.loading);

  const canPick = beat.included && !beat.loading && !locked;
  const canReinclude = !beat.included && !locked && Boolean(onToggleIncluded);
  // The row is one big target: a kept beat opens the clip picker, a removed
  // (dimmed) beat is added back. The checkbox is an explicit second affordance.
  const interactive = canPick || canReinclude;
  const activate = () => {
    if (canPick) onOpenPicker(index);
    else if (canReinclude) onToggleIncluded?.(index);
  };

  return (
    <li
      role={interactive ? "button" : undefined}
      tabIndex={interactive ? 0 : undefined}
      onClick={interactive ? activate : undefined}
      onKeyDown={
        interactive
          ? (e) => {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                activate();
              }
            }
          : undefined
      }
      aria-label={
        canPick ? "Change clip" : canReinclude ? "Add this beat back to the video" : undefined
      }
      className={cn(
        "group panel flex animate-fade-rise items-center gap-3 p-3 transition-colors hover:border-hairline/90 sm:gap-4 sm:p-4",
        !beat.included && "opacity-60",
        interactive &&
          "cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/60",
        canPick && "hover:border-accent/40",
        canReinclude && "hover:border-accent/40 hover:opacity-100",
      )}
      style={{ animationDelay: `${Math.min(index * 35, 500)}ms` }}
    >
      {!locked && onToggleIncluded && (
        // Generous hit area (the padded button) wrapping a clearly-sized box.
        <button
          type="button"
          role="checkbox"
          aria-checked={beat.included}
          aria-label={beat.included ? "Remove this beat from the video" : "Add this beat to the video"}
          title={beat.included ? "Remove from video" : "Add to video"}
          onClick={(e) => {
            e.stopPropagation();
            onToggleIncluded(index);
          }}
          className="-m-1.5 grid shrink-0 place-items-center self-center p-1.5 focus-visible:outline-none"
        >
          <span
            className={cn(
              "grid size-6 place-items-center rounded-md border-2 transition-all",
              "group-focus-visible:ring-0",
              beat.included
                ? "border-accent bg-accent text-accent-foreground"
                : "border-faint/70 bg-transparent text-transparent hover:border-cream",
            )}
          >
            <Check className="size-4" strokeWidth={3} />
          </span>
        </button>
      )}
      <div
        className={cn(
          "relative size-20 shrink-0 sm:size-24",
          !beat.included && "saturate-50",
        )}
      >
        <Thumb beat={beat} searching={searching} footageUrl={footageUrl} />
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
          {!beat.included && (
            <span className="rounded bg-panel-raised px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-faint">
              Removed
            </span>
          )}
        </div>
        {editing ? (
          <div
            onClick={(e) => e.stopPropagation()}
            onKeyDown={(e) => e.stopPropagation()}
          >
            <Textarea
              autoFocus
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              rows={2}
              disabled={saving}
              className="min-h-0 resize-none py-1.5 text-sm leading-relaxed"
              onKeyDown={(e) => {
                if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
                  e.preventDefault();
                  void saveEdit();
                } else if (e.key === "Escape") {
                  e.preventDefault();
                  cancelEdit();
                }
              }}
              onFocus={(e) => {
                const len = e.currentTarget.value.length;
                e.currentTarget.setSelectionRange(len, len);
              }}
            />
            <div className="mt-1.5 flex items-center gap-1.5">
              <Button
                size="sm"
                onClick={() => void saveEdit()}
                disabled={saving || !draft.trim() || draft.trim() === beat.text}
              >
                {saving ? (
                  <Loader2 className="size-3.5 animate-spin" />
                ) : (
                  <Check className="size-3.5" />
                )}
                {saving ? (isAnimated ? "Re-rendering…" : "Saving…") : "Save"}
              </Button>
              <Button size="sm" variant="ghost" onClick={cancelEdit} disabled={saving}>
                <X className="size-3.5" />
                Cancel
              </Button>
              <span className="hidden text-[11px] text-faint sm:inline">
                {isAnimated
                  ? "Fixes the text and re-renders the card"
                  : "Fixes the caption text only"}
              </span>
            </div>
          </div>
        ) : (
          <div className="flex items-start gap-1.5">
            <p
              className={cn(
                "min-w-0 flex-1 text-sm leading-relaxed text-cream/90",
                (beat.loading || !beat.included) && "text-faint",
                !beat.included && "line-through decoration-faint/60",
              )}
            >
              {showWords
                ? beat.words!.map((w, i) => (
                    <React.Fragment key={i}>
                      {i > 0 && " "}
                      <span
                        className={cn(
                          w.filler && "text-faint line-through decoration-accent/70 decoration-2",
                        )}
                      >
                        {w.text.trim()}
                      </span>
                    </React.Fragment>
                  ))
                : beat.text}
            </p>
            {canEditText && (
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  startEdit();
                }}
                className="mt-0.5 shrink-0 rounded p-1 text-faint opacity-0 transition-opacity hover:bg-panel-raised hover:text-cream focus-visible:opacity-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/60 group-hover:opacity-100"
                aria-label="Fix transcription typo"
                title="Fix transcription typo"
              >
                <Pencil className="size-3.5" />
              </button>
            )}
          </div>
        )}
      </div>

      {onPlayBeat && !beat.loading && (
        <Button
          size="icon-sm"
          variant="ghost"
          className="shrink-0 opacity-60 transition-opacity group-hover:opacity-100"
          onClick={(e) => {
            e.stopPropagation();
            onPlayBeat(index);
          }}
          aria-label="Play this beat"
          title="Play this beat"
        >
          <Play className="size-4" />
        </Button>
      )}

      {!locked &&
        (beat.included ? (
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
        ) : onToggleIncluded ? (
          <Button
            size="sm"
            variant="secondary"
            className="shrink-0"
            onClick={(e) => {
              e.stopPropagation();
              onToggleIncluded(index);
            }}
            aria-label="Add this beat back to the video"
            title="Add back to video"
          >
            <Plus className="size-4" />
            Add back
          </Button>
        ) : null)}
    </li>
  );
});
