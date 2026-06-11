"use client";

import * as React from "react";
import {
  CheckCircle2,
  Download,
  Pencil,
  RefreshCw,
  VideoOff,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { ThemeBadge } from "@/components/theme-badge";
import type { VideoJob } from "@/lib/types";
import { findChosenAsset, jobPhase, keptBeats, renderDurationSec } from "@/lib/store";
import { friendlyError } from "@/lib/errors";
import { fmtTime } from "@/lib/utils";
import { pickRenderScene, RenderSceneStage } from "@/components/render-scenes";

/**
 * The right-column panel shown while a render is in flight and once it's done.
 * State is derived from the job (which the editor keeps polling), so a page
 * refresh mid-render lands right back here on the correct step.
 */
export function RenderPanel({
  job,
  onEdit,
  onRetry,
}: {
  job: VideoJob;
  onEdit: () => void;
  onRetry: () => void;
}) {
  const phase = jobPhase(job);
  // Pick one whimsical scene per mount so each render feels a little different,
  // then cycle through that scene's own funny status lines.
  const [scene] = React.useState(pickRenderScene);
  const [line, setLine] = React.useState(0);

  React.useEffect(() => {
    if (phase !== "rendering") return;
    const t = setInterval(() => setLine((s) => (s + 1) % scene.lines.length), 2800);
    return () => clearInterval(t);
  }, [phase, scene.lines.length]);

  const poster = job.beats
    .filter((b) => b.included)
    .map(findChosenAsset)
    .find(Boolean);
  const showPosterVideoFrame =
    poster?.kind === "video" && Boolean(poster.mediaUrl);
  const posterVideoSrc = poster?.thumbUrl
    ? poster.mediaUrl
    : `${poster?.mediaUrl}#t=0.1`;
  const downloadUrl = `/api/videos/${job.id}/download`;

  return (
    <aside className="space-y-4 lg:sticky lg:top-[136px]">
      {phase === "failed" ? (
        <div className="panel p-6 text-center">
          {/* "Broken preview" placeholder — conveys something went wrong without
              leaking the raw backend error. */}
          <div className="mx-auto flex aspect-video w-full max-w-[220px] items-center justify-center rounded-xl border border-dashed border-destructive/40 bg-destructive/5">
            <div className="flex flex-col items-center gap-2 text-destructive/80">
              <VideoOff className="size-9" />
              <span className="flex gap-1">
                <span className="h-1 w-6 rounded-full bg-destructive/30" />
                <span className="h-1 w-3 rounded-full bg-destructive/20" />
                <span className="h-1 w-4 rounded-full bg-destructive/30" />
              </span>
            </div>
          </div>
          <h3 className="mt-4 font-heading text-lg font-bold text-cream">Something broke</h3>
          <p className="mt-1 text-xs text-faint">
            {friendlyError(
              job.error,
              "We hit a snag building your video. Nothing you did wrong — we're on it. Please try again.",
            )}
          </p>
          <div className="mt-5 flex flex-col gap-2">
            <Button variant="primary" className="w-full" onClick={onRetry}>
              <RefreshCw className="size-4" />
              Try again
            </Button>
            <Button variant="secondary" className="w-full" onClick={onEdit}>
              <Pencil className="size-4" />
              Back to editing
            </Button>
          </div>
        </div>
      ) : phase === "done" ? (
        <div className="panel p-6 text-center">
          <div className="mx-auto grid size-14 place-items-center rounded-full bg-accent/15 text-accent">
            <CheckCircle2 className="size-8" />
          </div>
          <h3 className="mt-4 font-heading text-xl font-bold text-cream">Your video is ready</h3>
          <p className="mt-1 font-mono text-[11px] text-faint">
            {job.aspect} · {fmtTime(renderDurationSec(job))} · {keptBeats(job).length} beats
          </p>
          <div className="mt-2 flex justify-center">
            <ThemeBadge theme={job.theme} />
          </div>
          <div className="relative mx-auto mt-4 aspect-[9/16] w-28 overflow-hidden rounded-xl border border-hairline bg-canvas">
            {showPosterVideoFrame ? (
              <video
                src={posterVideoSrc}
                poster={poster.thumbUrl || undefined}
                muted
                playsInline
                preload="metadata"
                className="size-full object-cover"
              />
            ) : poster?.thumbUrl ? (
              <img src={poster.thumbUrl} alt="" className="size-full object-cover" />
            ) : null}
          </div>
          <div className="mt-5 flex flex-col gap-2">
            <Button variant="primary" className="w-full" asChild>
              <a href={downloadUrl} download={`${job.id}.mp4`}>
                <Download className="size-4" />
                Download video
              </a>
            </Button>
            <Button variant="secondary" className="w-full" onClick={onEdit}>
              <Pencil className="size-4" />
              Back to editing
            </Button>
          </div>
        </div>
      ) : (
        // Rendering (queued or encoding).
        <div className="panel p-6 text-center">
          <RenderSceneStage scene={scene} />
          <p
            key={line}
            className="mx-auto mt-5 min-h-[2.75rem] max-w-[15rem] animate-fade-in font-heading text-lg font-bold leading-tight text-cream"
          >
            {scene.lines[line]}
          </p>
          <div className="mt-3 h-1.5 w-full overflow-hidden rounded-full bg-panel-raised">
            <div
              className="h-full rounded-full bg-accent transition-all duration-500 ease-out"
              style={{ width: `${Math.max(6, job.percent)}%` }}
            />
          </div>
          <p className="mt-2 font-mono text-[11px] text-faint/80">
            {job.stage === "render_queued" ? "Queued for rendering" : "Rendering"} · {job.percent}%
          </p>
          <div className="mt-3 flex justify-center">
            <ThemeBadge theme={job.theme} />
          </div>
          <p className="mt-3 text-[11px] text-faint/60">
            {job.slow
              ? "This is taking longer than usual, but it's still running. You can safely leave or refresh — we'll pick up where it left off."
              : "This can take a few minutes. You can safely leave or refresh this page — we'll pick up right where it left off."}
          </p>
        </div>
      )}
    </aside>
  );
}
