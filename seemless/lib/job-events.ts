// Live job-progress channel (Server-Sent Events).
//
// Subscribes to the same-origin proxy `/api/jobs/{id}/events`, which injects the
// Supabase bearer server-side and pipes the orchestrator's text/event-stream
// through. This drives the live progress bar ("Transcribing… / Rendering 43%…")
// without aggressively polling the JSON status endpoint. The browser's
// EventSource auto-reconnects on a dropped connection, so callers only need to
// close it when they're done.

export type JobEvent = {
  job_id: string;
  // Orchestrator status enum (queued/transcribing/.../rendering/done/failed).
  status: string;
  stage: string | null;
  percent: number | null;
  error: string | null;
  // Short-lived signed download URL, present only once status === "done".
  result_url?: string | null;
};

export type JobEventsHandle = { close: () => void };

export function subscribeJobEvents(
  id: string,
  handlers: {
    onUpdate: (e: JobEvent) => void;
    onEnd?: () => void;
    onError?: () => void;
  },
): JobEventsHandle {
  // SSR / unsupported environments: no-op handle (caller falls back to polling).
  if (typeof window === "undefined" || typeof EventSource === "undefined") {
    return { close: () => {} };
  }

  const es = new EventSource(`/api/jobs/${encodeURIComponent(id)}/events`);
  let closed = false;
  const close = () => {
    if (closed) return;
    closed = true;
    es.close();
  };

  es.onmessage = (ev) => {
    if (!ev.data) return;
    try {
      handlers.onUpdate(JSON.parse(ev.data) as JobEvent);
    } catch {
      // Ignore a malformed frame; the next tick supersedes it.
    }
  };

  // The server emits a terminal `end` event on done/failed (or if the job is
  // gone) and then closes — stop here rather than letting EventSource reconnect.
  es.addEventListener("end", () => {
    handlers.onEnd?.();
    close();
  });

  es.onerror = () => {
    // Transient drop: EventSource reconnects on its own. Surface a hook so the
    // caller can lean on its polling fallback in the meantime.
    handlers.onError?.();
  };

  return { close };
}
