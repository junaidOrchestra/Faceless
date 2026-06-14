"use client";

import * as React from "react";
import { useParams, useRouter } from "next/navigation";
import { Loader2 } from "lucide-react";
import { TopBar } from "@/components/topbar";
import { Storyboard } from "@/components/storyboard";
import { Sidebar } from "@/components/sidebar";
import { ClipPicker, NewAnimatedBeatDialog } from "@/components/clip-picker";
import { PreviewPlayer } from "@/components/preview-player";
import { RenderPanel } from "@/components/render-panel";
import {
  chosenCount,
  jobPhase,
  stepKeyForPhase,
  useEditorStore,
} from "@/lib/store";
import { useBackgroundUpload } from "@/lib/background-upload";

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
  const toggleBeat = useEditorStore((s) => s.toggleBeat);
  const setAllBeatsIncluded = useEditorStore((s) => s.setAllBeatsIncluded);
  const editBeatText = useEditorStore((s) => s.editBeatText);
  const splitBeat = useEditorStore((s) => s.splitBeat);
  const mergeBeatWithNext = useEditorStore((s) => s.mergeBeatWithNext);

  const [pickerBeat, setPickerBeat] = React.useState<number | null>(null);
  const [insertPosition, setInsertPosition] = React.useState<number | null>(null);
  // Beat being auditioned on its own via the per-row play button (null = closed).
  const [previewBeat, setPreviewBeat] = React.useState<number | null>(null);
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
  const playBeat = React.useCallback((beatIndex: number) => {
    setPreviewBeat(beatIndex);
  }, []);
  const onEditText = React.useCallback(
    (beatIndex: number, text: string) => editBeatText(beatIndex, text),
    [editBeatText],
  );
  const onSplitBeat = React.useCallback(
    (beatIndex: number, wordIndex: number) => splitBeat(beatIndex, wordIndex),
    [splitBeat],
  );
  const onMergeBeat = React.useCallback(
    (beatIndex: number) => mergeBeatWithNext(beatIndex),
    [mergeBeatWithNext],
  );

  // Edit-while-uploading: gate rendering until the background video upload
  // completes. `uploadPending` (server-truth) survives a refresh; the live
  // background-upload state adds an instant percentage when present. Called
  // before any early return so hook order stays stable.
  const bgUpload = useBackgroundUpload(job?.id);

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
  const uploadActive = bgUpload?.status === "uploading";
  const uploadPending = Boolean(job.uploadPending) || uploadActive;
  const uploadPercent = uploadActive ? Math.round(bgUpload?.percent ?? 0) : undefined;
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
        uploadPending={uploadPending}
        uploadPercent={uploadPercent}
      />

      <main className="mx-auto grid max-w-7xl grid-cols-1 gap-6 px-4 py-6 sm:px-6 lg:grid-cols-[1fr_340px]">
        <div className="min-w-0">
          <Storyboard
            job={job}
            phase={phase}
            stage={job.stage}
            locked={showRender}
            onOpenPicker={openPicker}
            onToggleIncluded={toggleBeat}
            onSetAllIncluded={setAllBeatsIncluded}
            onPlayBeat={playBeat}
            onAddTextBeat={setInsertPosition}
            onEditText={onEditText}
            onSplitBeat={onSplitBeat}
            onMergeBeat={onMergeBeat}
          />
        </div>
        {showRender ? (
          <RenderPanel
            job={job}
            onEdit={() => setEditingAfterDone(true)}
            onRetry={onMakeVideo}
          />
        ) : (
          <Sidebar
            job={job}
            chosen={chosen}
            total={total}
            onMakeVideo={onMakeVideo}
            uploadPending={uploadPending}
            uploadPercent={uploadPercent}
          />
        )}
      </main>

      <ClipPicker
        key={pickerBeat ?? "closed"}
        beat={openBeat}
        open={pickerBeat !== null && !showRender}
        onClose={() => setPickerBeat(null)}
      />

      <NewAnimatedBeatDialog
        key={insertPosition ?? "insert-closed"}
        position={insertPosition}
        open={insertPosition !== null && !showRender}
        onClose={() => setInsertPosition(null)}
      />

      <PreviewPlayer
        key={previewBeat ?? "preview-closed"}
        job={job}
        beatIndex={previewBeat}
        open={previewBeat !== null}
        onClose={() => setPreviewBeat(null)}
      />
    </div>
  );
}
