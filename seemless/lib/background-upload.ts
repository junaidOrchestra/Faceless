"use client";

import * as React from "react";

/**
 * Tracks a video upload that continues after the editor opens.
 *
 * When client audio extraction succeeds we start the job from the WAV and let the
 * user edit immediately while the full video uploads in the background. The
 * module-level state survives in-app navigation; a beforeunload guard warns if
 * the tab is closed mid-upload.
 */

import { uploadFileMultipart } from "./b2-upload";
import {
  orchFinalizeUpload,
  orchPutObject,
  orchRequestUploadSlot,
  orchStartFromAudio,
} from "./orchestrator";
import type { UploadSlot } from "./orchestrator";
import { tryExtractTranscribeWav } from "./extract-audio";

export type BackgroundUploadState = {
  jobId: string;
  fileName: string;
  percent: number;
  status: "uploading" | "done" | "error";
  error?: string;
};

type Listener = (state: BackgroundUploadState | null) => void;

let active: BackgroundUploadState | null = null;
const listeners = new Set<Listener>();
let unloadBound = false;

function emit(): void {
  for (const fn of listeners) fn(active);
}

function bindUnloadGuard(): void {
  if (unloadBound || typeof window === "undefined") return;
  unloadBound = true;
  window.addEventListener("beforeunload", (e) => {
    if (active?.status === "uploading") {
      e.preventDefault();
      e.returnValue = "";
    }
  });
}

export function subscribeBackgroundUpload(fn: Listener): () => void {
  listeners.add(fn);
  fn(active);
  return () => listeners.delete(fn);
}

export function getBackgroundUpload(jobId: string): BackgroundUploadState | null {
  return active?.jobId === jobId ? active : null;
}

export function isBackgroundUploading(jobId?: string): boolean {
  if (!active || active.status !== "uploading") return false;
  return jobId ? active.jobId === jobId : true;
}

/**
 * React hook: live background-upload state for `jobId` (or null when none is
 * active for it). Re-renders as the upload progresses / completes.
 */
export function useBackgroundUpload(
  jobId: string | undefined,
): BackgroundUploadState | null {
  const subscribe = React.useCallback(
    (cb: () => void) => subscribeBackgroundUpload(() => cb()),
    [],
  );
  const getSnapshot = React.useCallback(
    () => (jobId ? getBackgroundUpload(jobId) : null),
    [jobId],
  );
  return React.useSyncExternalStore(subscribe, getSnapshot, () => null);
}

/**
 * Try the edit-while-uploading path for a video file:
 *  1. extract a small narration WAV in the browser,
 *  2. PUT it to the bucket and start the job transcribing from it,
 *  3. let the user edit immediately while the full video uploads in the
 *     background (finalized when complete).
 *
 * Returns the job id on success, or `null` when the fast path is unavailable
 * (audio extraction failed, or the backend has no direct-upload storage), so the
 * caller can fall back to a regular foreground upload.
 */
export async function startVideoWithEarlyTranscribe(
  file: File,
  signal?: AbortSignal,
): Promise<string | null> {
  let wav: Blob | null = null;
  try {
    wav = await tryExtractTranscribeWav(file);
  } catch (e) {
    console.warn("[bg-upload] audio extraction failed; falling back", e);
    wav = null;
  }
  if (!wav) return null;

  const slot = await orchRequestUploadSlot(file, { withAudio: true });
  if (!slot || !slot.audioPutUrl || !slot.audioObject) return null;

  // Past this point the early path is committed: errors propagate (we don't
  // silently fall back, which would create a duplicate job).
  await orchPutObject(slot.audioPutUrl, wav, signal);
  const { videoJobId } = await orchStartFromAudio(slot, file);
  startBackgroundVideoUpload(slot, file);
  return videoJobId;
}

/** Fire-and-forget: upload the video and finalize when done. */
export function startBackgroundVideoUpload(
  slot: UploadSlot,
  file: File,
  transcribeAudioObject?: string,
): void {
  if (!slot.objectKey || !slot.uploadId || !slot.partUrls.length || !slot.partSizeBytes) {
    console.error("[bg-upload] invalid upload slot");
    return;
  }

  active = {
    jobId: slot.videoJobId,
    fileName: file.name,
    percent: 0,
    status: "uploading",
  };
  bindUnloadGuard();
  emit();

  void (async () => {
    try {
      const parts = await uploadFileMultipart(
        file,
        slot.partUrls,
        slot.partSizeBytes,
        (pct) => {
          if (active?.jobId === slot.videoJobId) {
            active = { ...active, percent: pct };
            emit();
          }
        },
      );
      await orchFinalizeUpload(slot, file, parts, undefined, transcribeAudioObject);
      if (active?.jobId === slot.videoJobId) {
        active = { ...active, percent: 100, status: "done" };
        emit();
        console.info(`[bg-upload] complete for job ${slot.videoJobId}`);
      }
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Upload failed";
      console.error(`[bg-upload] failed for job ${slot.videoJobId}`, e);
      if (active?.jobId === slot.videoJobId) {
        active = { ...active, status: "error", error: msg };
        emit();
      }
    }
  })();
}
