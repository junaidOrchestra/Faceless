"use client";

import { AlertTriangle, AudioLines, Loader2, Sparkles } from "lucide-react";
import { BeatRow } from "@/components/beat-row";
import { SetupCard } from "@/components/setup-card";
import { Skeleton } from "@/components/ui/skeleton";
import type { Beat, VideoJob } from "@/lib/types";
import type { JobPhase } from "@/lib/store";

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

export function Storyboard({
  job,
  phase,
  stage,
  locked = false,
  onOpenPicker,
}: {
  job: VideoJob;
  phase: JobPhase;
  stage: string;
  locked?: boolean;
  onOpenPicker: (beatIndex: number) => void;
}) {
  const beats = job.beats;

  if (phase === "failed") {
    return (
      <section>
        <h2 className="mb-4 font-heading text-xl font-semibold text-cream">Storyboard</h2>
        <div className="panel flex items-start gap-3 border-destructive/40 p-4">
          <AlertTriangle className="mt-0.5 size-5 shrink-0 text-destructive" />
          <div>
            <p className="text-sm font-medium text-cream">Processing failed</p>
            <p className="text-xs text-faint">
              {job.error || stage || "The pipeline could not finish this job."}
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
              ? `${beats.length} beats · view only`
              : setup
                ? hasBeats
                  ? `${beats.length} beats · review`
                  : "transcribing…"
                : `${beats.length} beats`}
          </span>
        )}
      </div>

      {job.slow && <SlowNote />}

      {setup && <SetupCard job={job} transcribing={!hasBeats} />}

      {hasBeats ? (
        <ol className="space-y-3">
          {beats.map((beat) => (
            <BeatRow
              key={beat.index}
              beat={beat}
              index={beat.index}
              searching={searching}
              locked={locked}
              onOpenPicker={onOpenPicker}
            />
          ))}
        </ol>
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
