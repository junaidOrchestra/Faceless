"use client";

import * as React from "react";
import { getUploadedMediaUrl, hydrateUploadedMediaUrl } from "./preview-audio";

/**
 * Local object URL for a user-uploaded video job's footage, for display in the
 * editor preview / thumbnails. Returns the in-session URL synchronously when
 * available, otherwise rehydrates it from the IndexedDB cache. Resolves to null
 * for non-video jobs or when no local copy exists on this device (the caller
 * should then fall back to the cloud media_url).
 */
export function useLocalFootageUrl(
  jobId: string | undefined,
  isVideo: boolean | undefined,
): string | null {
  // Synchronous in-session URL (available immediately after upload). Derived in
  // render so a job change can't briefly surface a stale value.
  const sync = isVideo && jobId ? getUploadedMediaUrl(jobId) ?? null : null;
  // Async-rehydrated URL (after a refresh / direct visit), keyed by job id.
  const [hydrated, setHydrated] = React.useState<{
    jobId: string;
    url: string | null;
  } | null>(null);

  React.useEffect(() => {
    if (!isVideo || !jobId || getUploadedMediaUrl(jobId)) return;
    let cancelled = false;
    void hydrateUploadedMediaUrl(jobId).then((resolved) => {
      if (!cancelled) setHydrated({ jobId, url: resolved });
    });
    return () => {
      cancelled = true;
    };
  }, [jobId, isVideo]);

  if (sync) return sync;
  if (hydrated && hydrated.jobId === jobId) return hydrated.url;
  return null;
}
