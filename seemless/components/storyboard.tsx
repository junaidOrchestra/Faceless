"use client";

import * as React from "react";
import {
  AlertTriangle,
  AudioLines,
  CheckSquare,
  Loader2,
  Plus,
  Search,
  Sparkles,
  Square,
  X,
} from "lucide-react";
import { BeatRow } from "@/components/beat-row";
import { SetupCard } from "@/components/setup-card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import type { VideoJob } from "@/lib/types";
import { keptBeats, type JobPhase } from "@/lib/store";
import { friendlyError } from "@/lib/errors";
import { useLocalFootageUrl } from "@/lib/use-local-footage";

function GhostRows({ count = 6 }: { count?: number }) {
  return (
    <ol className="space-y-3">
      {Array.from({ length: count }).map((_, i) => (
        <li key={i} className="panel flex items-start gap-4 p-3 sm:p-4">
          <Skeleton className="size-20 shrink-0 rounded-lg sm:size-24" />
          <div className="flex-1 space-y-2 py-1">
            <Skeleton className="h-3 w-24" />
            <Skeleton className="h-3 w-full" />
            <Skeleton className="h-3 w-2/3" />
          </div>
        </li>
      ))}
    </ol>
  );
}

function SlowNote() {
  return (
    <div className="panel mb-3 flex items-start gap-3 border-accent/30 p-3">
      <AlertTriangle className="mt-0.5 size-4 shrink-0 text-accent" />
      <p className="text-xs text-faint">
        This is taking longer than expected. It&apos;s still running — you can keep
        waiting, or come back in a bit.
      </p>
    </div>
  );
}

function StatusBanner({ title, subtitle }: { title: string; subtitle: string }) {
  return (
    <div className="panel mb-3 flex items-center gap-3 p-4">
      <span className="grid size-10 shrink-0 place-items-center rounded-lg bg-panel-raised text-accent">
        <AudioLines className="size-5" />
      </span>
      <div className="min-w-0">
        <p className="flex items-center gap-2 text-sm font-medium text-cream">
          <Loader2 className="size-3.5 animate-spin text-accent" />
          {title}
        </p>
        <p className="text-xs text-faint">{subtitle}</p>
      </div>
    </div>
  );
}

// Settings committed, but beats aren't ready yet (transcription / LLM still
// running). The clip search starts automatically the moment they are.
function PreparingState({ stage, slow }: { stage: string; slow?: boolean }) {
  return (
    <section>
      <div className="mb-4 flex items-baseline justify-between">
        <h2 className="font-heading text-xl font-semibold text-cream">Storyboard</h2>
        <span className="text-xs text-faint">setup saved</span>
      </div>
      {slow && <SlowNote />}
      <StatusBanner
        title={stage || "Finishing transcription"}
        subtitle="Your output is set — we'll start finding clips as soon as the beats are ready."
      />
      <GhostRows />
    </section>
  );
}

function AddTextBeatButton({
  position,
  onAdd,
}: {
  position: number;
  onAdd?: (position: number) => void;
}) {
  if (!onAdd) return null;
  return (
    <li className="flex justify-center py-1">
      <Button
        type="button"
        size="sm"
        variant="ghost"
        className="border border-dashed border-hairline/80 bg-panel-raised/30 text-faint hover:text-cream"
        onClick={() => onAdd(position)}
      >
        <Plus className="size-3.5" />
        Add text card
      </Button>
    </li>
  );
}

export function Storyboard({
  job,
  phase,
  stage,
  locked = false,
  onOpenPicker,
  onToggleIncluded,
  onSetAllIncluded,
  onPlayBeat,
  onAddTextBeat,
  onEditText,
}: {
  job: VideoJob;
  phase: JobPhase;
  stage: string;
  locked?: boolean;
  onOpenPicker: (beatIndex: number) => void;
  onToggleIncluded?: (beatIndex: number) => void;
  onSetAllIncluded?: (included: boolean) => void;
  onPlayBeat?: (beatIndex: number) => void;
  onAddTextBeat?: (position: number) => void;
  onEditText?: (beatIndex: number, text: string) => void | Promise<void>;
}) {
  const beats = job.beats;
  const kept = keptBeats(job);
  const [query, setQuery] = React.useState("");
  // Local copy of the uploaded video, used to render "your footage" thumbnails
  // from the user's machine instead of the cloud original.
  const footageUrl = useLocalFootageUrl(job.id, job.isVideo);

  const trimmedQuery = query.trim().toLowerCase();
  const visibleBeats = React.useMemo(() => {
    if (!trimmedQuery) return beats;
    return beats.filter((b) =>
      `${b.text} ${b.overlay ?? ""}`.toLowerCase().includes(trimmedQuery),
    );
  }, [beats, trimmedQuery]);

  if (phase === "failed") {
    return (
      <section>
        <h2 className="mb-4 font-heading text-xl font-semibold text-cream">Storyboard</h2>
        <div className="panel flex items-start gap-3 border-destructive/40 p-4">
          <AlertTriangle className="mt-0.5 size-5 shrink-0 text-destructive" />
          <div>
            <p className="text-sm font-medium text-cream">Something broke</p>
            <p className="text-xs text-faint">
              {friendlyError(
                job.error,
                "We couldn't finish processing this video. Our team's been notified — please try again.",
              )}
            </p>
          </div>
        </div>
      </section>
    );
  }

  if (phase === "preparing") {
    return <PreparingState stage={stage} slow={job.slow} />;
  }

  const searching = phase === "searching";
  const setup = phase === "setup";
  const hasBeats = beats.length > 0;
  const loadingCount = beats.filter((b) => b.loading).length;

  return (
    <section>
      <div className="mb-4 flex items-baseline justify-between gap-3">
        <h2 className="font-heading text-xl font-semibold text-cream">Storyboard</h2>
        {searching ? (
          <span className="flex items-center gap-1.5 text-xs text-accent">
            <Sparkles className="size-3.5" />
            finding clips · {loadingCount} left
          </span>
        ) : (
          <span className="text-xs text-faint">
            {locked
              ? `${kept.length} of ${beats.length} beats · view only`
              : setup
                ? hasBeats
                  ? `${kept.length} of ${beats.length} beats · review`
                  : "transcribing…"
                : kept.length < beats.length
                  ? `${kept.length} of ${beats.length} beats`
                  : `${beats.length} beats`}
          </span>
        )}
      </div>

      {job.slow && <SlowNote />}

      {setup && <SetupCard job={job} transcribing={!hasBeats} />}

      {!locked && hasBeats && onSetAllIncluded && (
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2 rounded-lg border border-hairline bg-panel-raised/40 px-3 py-2">
          <p className="text-xs text-faint">
            Tick the beats to keep.{" "}
            <span className="font-medium text-cream">{kept.length}</span> of {beats.length} in
            your video
          </p>
          <div className="flex items-center gap-1">
            <Button
              size="sm"
              variant="ghost"
              onClick={() => onSetAllIncluded(true)}
              disabled={kept.length === beats.length}
            >
              <CheckSquare className="size-3.5" />
              Select all
            </Button>
            <Button
              size="sm"
              variant="ghost"
              onClick={() => onSetAllIncluded(false)}
              disabled={kept.length === 0}
            >
              <Square className="size-3.5" />
              Deselect all
            </Button>
          </div>
        </div>
      )}

      {hasBeats ? (
        <>
          <div className="relative mb-3">
            <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-faint" />
            <Input
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search beats by text…"
              aria-label="Search beats"
              className="pl-9 pr-9"
            />
            {query && (
              <button
                type="button"
                onClick={() => setQuery("")}
                aria-label="Clear search"
                className="absolute right-2 top-1/2 grid size-6 -translate-y-1/2 place-items-center rounded-md text-faint hover:bg-panel-raised hover:text-cream"
              >
                <X className="size-4" />
              </button>
            )}
          </div>

          {visibleBeats.length > 0 ? (
            <div className="-mr-1 max-h-[65vh] overflow-y-auto pr-1 lg:max-h-[calc(100vh-200px)]">
              <ol className="space-y-3">
                {!locked && !trimmedQuery && !searching && (
                  <AddTextBeatButton position={0} onAdd={onAddTextBeat} />
                )}
                {visibleBeats.map((beat) => (
                  <React.Fragment key={beat.index}>
                    <BeatRow
                      beat={beat}
                      index={beat.index}
                      searching={searching}
                      locked={locked}
                      strikeFillers={job.removeFillers}
                      footageUrl={footageUrl}
                      onOpenPicker={onOpenPicker}
                      onToggleIncluded={onToggleIncluded}
                      onPlayBeat={onPlayBeat}
                      onEditText={onEditText}
                    />
                    {!locked && !trimmedQuery && !searching && (
                      <AddTextBeatButton position={beat.index + 1} onAdd={onAddTextBeat} />
                    )}
                  </React.Fragment>
                ))}
              </ol>
            </div>
          ) : (
            <div className="panel flex flex-col items-center gap-1 p-8 text-center">
              <p className="text-sm font-medium text-cream">No beats match “{query}”</p>
              <button
                type="button"
                onClick={() => setQuery("")}
                className="text-xs font-medium text-accent hover:underline"
              >
                Clear search
              </button>
            </div>
          )}
        </>
      ) : (
        // Setup is committed-or-pending but beats haven't arrived. Show the
        // background transcription progress beneath the form.
        <>
          {setup && (
            <StatusBanner
              title={stage || "Transcribing narration"}
              subtitle="Splitting your audio into spoken beats — they'll appear here in a moment."
            />
          )}
          <GhostRows />
        </>
      )}
    </section>
  );
}
