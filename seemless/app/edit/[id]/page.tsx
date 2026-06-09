"use client";

import * as React from "react";
import { useParams, useRouter } from "next/navigation";
import { Loader2 } from "lucide-react";
import { TopBar } from "@/components/topbar";
import { Storyboard } from "@/components/storyboard";
import { Sidebar } from "@/components/sidebar";
import { ClipPicker } from "@/components/clip-picker";
import { RenderPanel } from "@/components/render-panel";
import {
  chosenCount,
  jobPhase,
  stepKeyForPhase,
  useEditorStore,
} from "@/lib/store";

export default function EditorPage() {
  const params = useParams<{ id: string }>();
  const id = params.id;
  const router = useRouter();

  const job = useEditorStore((s) => s.job);
  const loading = useEditorStore((s) => s.loading);
  const notFound = useEditorStore((s) => s.notFound);
  const load = useEditorStore((s) => s.load);
  const stopPolling = useEditorStore((s) => s.stopPolling);
  const render = useEditorStore((s) => s.render);

  const [pickerBeat, setPickerBeat] = React.useState<number | null>(null);
  // Lets the user step back from a finished render to keep editing (ephemeral —
  // a refresh re-derives the phase from the job, landing back on the result).
  const [editingAfterDone, setEditingAfterDone] = React.useState(false);

  React.useEffect(() => {
    if (id) void load(id);
    return () => stopPolling();
  }, [id, load, stopPolling]);

  // The job is missing or belongs to another user: show a brief notice, then
  // send the user back to the home page (replace so Back doesn't loop here).
  React.useEffect(() => {
    if (!notFound) return;
    const t = setTimeout(() => router.replace("/"), 1800);
    return () => clearTimeout(t);
  }, [notFound, router]);

  const onMakeVideo = React.useCallback(() => {
    setEditingAfterDone(false);
    void render();
  }, [render]);
  const openPicker = React.useCallback((beatIndex: number) => {
    setPickerBeat(beatIndex);
  }, []);

  // The narration filename isn't carried across the upload navigation, so the
  // upload screen stashes it in sessionStorage keyed by job id.
  const storedName =
    typeof window !== "undefined" ? sessionStorage.getItem(`sf:name:${id}`) : null;

  if (notFound) {
    return (
      <div className="grid min-h-screen place-items-center text-faint">
        <div className="flex max-w-sm flex-col items-center gap-3 text-center">
          <h1 className="font-heading text-xl font-bold text-cream">
            Project not found
          </h1>
          <p className="text-sm">
            This project doesn’t exist or isn’t available on your account. Taking
            you back to the home page…
          </p>
          <button
            type="button"
            onClick={() => router.replace("/")}
            className="text-sm font-medium text-accent hover:underline"
          >
            Go to home now
          </button>
        </div>
      </div>
    );
  }

  if (loading || !job) {
    return (
      <div className="grid min-h-screen place-items-center text-faint">
        <div className="flex flex-col items-center gap-3">
          <Loader2 className="size-7 animate-spin text-accent" />
          <p className="text-sm">Loading your storyboard…</p>
        </div>
      </div>
    );
  }

  const { chosen, total } = chosenCount(job);
  const phase = jobPhase(job);
  // The render view owns the screen while rendering (can't be dismissed) and
  // after it's done (until the user chooses to keep editing).
  const showRender = phase === "rendering" || phase === "failed" || (phase === "done" && !editingAfterDone);
  const busy = phase === "rendering";
  const openBeat =
    pickerBeat !== null ? job.beats.find((b) => b.index === pickerBeat) ?? null : null;

  return (
    <div className="min-h-screen">
      <TopBar
        fileName={job.fileName ?? storedName ?? "narration.mp3"}
        duration={job.durationSec ?? 0}
        audioUrl={job.audioUrl}
        chosen={chosen}
        total={total}
        stepKey={stepKeyForPhase(phase)}
        onMakeVideo={onMakeVideo}
        busy={busy}
        hideMakeVideo={showRender}
      />

      <main className="mx-auto grid max-w-7xl grid-cols-1 gap-6 px-4 py-6 sm:px-6 lg:grid-cols-[1fr_340px]">
        <div className="min-w-0">
          <Storyboard
            job={job}
            phase={phase}
            stage={job.stage}
            locked={showRender}
            onOpenPicker={openPicker}
          />
        </div>
        {showRender ? (
          <RenderPanel
            job={job}
            onEdit={() => setEditingAfterDone(true)}
            onRetry={onMakeVideo}
          />
        ) : (
          <Sidebar job={job} chosen={chosen} total={total} onMakeVideo={onMakeVideo} />
        )}
      </main>

      <ClipPicker
        key={pickerBeat ?? "closed"}
        beat={openBeat}
        open={pickerBeat !== null && !showRender}
        onClose={() => setPickerBeat(null)}
      />
    </div>
  );
}
