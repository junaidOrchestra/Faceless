"use client";

import * as React from "react";
import {
  Clapperboard,
  Music,
  Captions,
  Play,
  ImageIcon,
  Gauge,
  Lock,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { Badge } from "@/components/ui/badge";
import { ThemeBadge } from "@/components/theme-badge";
import { PreviewPlayer } from "@/components/preview-player";
import type { Aspect, VideoJob } from "@/lib/types";
import { ASPECTS, findChosenAsset, QUALITIES, useEditorStore } from "@/lib/store";
import { cn } from "@/lib/utils";

const ASPECT_BOX: Record<Aspect, string> = {
  "9:16": "aspect-[9/16] w-32",
  "16:9": "aspect-video w-full",
  "1:1": "aspect-square w-44",
};

function PreviewFrame({ job }: { job: VideoJob }) {
  // The box is a poster; pressing play opens the full-size player popup.
  const firstChosen = job.beats.map(findChosenAsset).find(Boolean);
  const hasContent = job.beats.length > 0;
  const showVideoFrame =
    firstChosen?.kind === "video" && Boolean(firstChosen.mediaUrl);
  const previewVideoSrc = firstChosen?.thumbUrl
    ? firstChosen.mediaUrl
    : `${firstChosen?.mediaUrl}#t=0.1`;
  const [open, setOpen] = React.useState(false);

  return (
    <div className="flex flex-col items-center gap-2">
      <div
        className={cn(
          "relative overflow-hidden rounded-xl border border-hairline bg-black",
          ASPECT_BOX[job.aspect],
        )}
      >
        {showVideoFrame ? (
          <video
            src={previewVideoSrc}
            poster={firstChosen.thumbUrl || undefined}
            muted
            playsInline
            preload="metadata"
            className="size-full object-cover opacity-80"
          />
        ) : firstChosen?.thumbUrl ? (
          <img src={firstChosen.thumbUrl} alt="" className="size-full object-cover opacity-80" />
        ) : (
          <div className="grid size-full place-items-center text-faint">
            <ImageIcon className="size-6" />
          </div>
        )}
        <div className="absolute inset-0 bg-gradient-to-t from-black/60 via-transparent to-black/20" />

        <button
          className="absolute inset-0 grid place-items-center"
          aria-label="Play preview"
          type="button"
          onClick={() => setOpen(true)}
          disabled={!hasContent}
        >
          <span className="grid size-11 place-items-center rounded-full bg-accent/90 text-accent-foreground shadow-lg backdrop-blur transition-transform hover:scale-105">
            <Play className="size-5 translate-x-0.5" fill="currentColor" />
          </span>
        </button>

        {job.captions && (
          <span className="absolute bottom-2 left-1/2 -translate-x-1/2 whitespace-nowrap rounded bg-black/70 px-2 py-0.5 text-[10px] font-medium text-white backdrop-blur">
            Captions on
          </span>
        )}
      </div>
      <p className="text-[11px] text-faint">Preview rough cut</p>

      <PreviewPlayer
        key={open ? "preview-open" : "preview-closed"}
        job={job}
        open={open}
        onClose={() => setOpen(false)}
      />
    </div>
  );
}

const SOURCES = [
  { key: "pexels", label: "Pexels" },
  { key: "wikimedia", label: "Wikimedia" },
  { key: "yours", label: "Your library", highlight: true },
];

export function Sidebar({
  job,
  chosen,
  total,
  onMakeVideo,
}: {
  job: VideoJob;
  chosen: number;
  total: number;
  onMakeVideo: () => void;
}) {
  const updateSettings = useEditorStore((s) => s.updateSettings);
  const ready = total > 0 && chosen >= total;
  const pct = total > 0 ? Math.round((chosen / total) * 100) : 0;
  // Aspect/quality drive the clip search, so they lock once it has started.
  const locked = Boolean(job.prepared);

  return (
    <aside className="space-y-4 lg:sticky lg:top-[136px]">
      <div className="panel p-4">
        <PreviewFrame job={job} />
      </div>

      <div className="panel space-y-2 p-4">
        <h3 className="font-heading text-sm font-semibold text-cream">Content theme</h3>
        <ThemeBadge theme={job.theme} />
        <p className="text-xs text-faint">
          {job.theme.mode === "vibe"
            ? "Clips come from this vibe, not your narration."
            : "Clips are matched to what your narration says."}
        </p>
      </div>

      <div className="panel space-y-4 p-4">
        <div className="flex items-center justify-between">
          <h3 className="font-heading text-sm font-semibold text-cream">Output</h3>
          {locked && (
            <span className="flex items-center gap-1 text-[11px] text-faint">
              <Lock className="size-3" /> locked
            </span>
          )}
        </div>

        <div>
          <p className="mb-2 text-xs text-faint">Aspect ratio</p>
          <div className="flex gap-2">
            {ASPECTS.map((a) => (
              <button
                key={a}
                type="button"
                disabled={locked}
                onClick={() => updateSettings({ aspect: a })}
                className={cn(
                  "flex-1 rounded-lg border px-2 py-1.5 font-mono text-xs transition-all disabled:cursor-not-allowed disabled:opacity-60",
                  job.aspect === a
                    ? "border-accent bg-accent/10 text-accent"
                    : "border-hairline text-faint enabled:hover:border-hairline/80 enabled:hover:text-cream",
                )}
              >
                {a}
              </button>
            ))}
          </div>
        </div>

        <div>
          <p className="mb-2 flex items-center gap-1.5 text-xs text-faint">
            <Gauge className="size-3.5" /> Quality
          </p>
          <div className="flex gap-2">
            {QUALITIES.map((q) => (
              <button
                key={q.value}
                type="button"
                disabled={locked}
                onClick={() => updateSettings({ quality: q.value })}
                className={cn(
                  "flex-1 rounded-lg border px-2 py-1.5 text-xs transition-all disabled:cursor-not-allowed disabled:opacity-60",
                  job.quality === q.value
                    ? "border-accent bg-accent/10 text-accent"
                    : "border-hairline text-faint enabled:hover:border-hairline/80 enabled:hover:text-cream",
                )}
              >
                {q.label}
              </button>
            ))}
          </div>
        </div>

        <label className="flex items-center justify-between">
          <span className="flex items-center gap-2 text-sm text-cream">
            <Captions className="size-4 text-faint" />
            Captions
          </span>
          <Switch
            checked={job.captions}
            onCheckedChange={(v) => updateSettings({ captions: v })}
          />
        </label>

        <label className="flex items-center justify-between">
          <span className="flex items-center gap-2 text-sm text-cream">
            <Music className="size-4 text-faint" />
            Background music
          </span>
          <Switch
            checked={job.music}
            onCheckedChange={(v) => updateSettings({ music: v })}
          />
        </label>
      </div>

      <div className="panel space-y-3 p-4">
        <div className="flex items-center justify-between">
          <h3 className="font-heading text-sm font-semibold text-cream">Clips chosen</h3>
          <span className="font-mono text-xs text-faint">
            {chosen} of {total}
          </span>
        </div>
        <div className="relative h-2 w-full overflow-hidden rounded-full bg-panel-raised">
          <div
            className="absolute inset-y-0 left-0 rounded-full bg-accent transition-[width] duration-500 ease-out"
            style={{ width: `${pct}%` }}
          />
        </div>
        <p className="text-xs text-faint">
          {ready
            ? "Every beat has a visual. You're ready to render."
            : `${total - chosen} ${total - chosen === 1 ? "beat" : "beats"} still need a visual.`}
        </p>
      </div>

      <div className="panel space-y-3 p-4">
        <h3 className="font-heading text-sm font-semibold text-cream">Sources</h3>
        <div className="flex flex-wrap gap-2">
          {SOURCES.map((s) => (
            <Badge key={s.key} variant={s.highlight ? "accent" : "default"}>
              {s.label}
            </Badge>
          ))}
        </div>
      </div>

      <Button variant="primary" className="w-full" disabled={!ready} onClick={onMakeVideo}>
        <Clapperboard className="size-4" />
        Make video
      </Button>
    </aside>
  );
}
