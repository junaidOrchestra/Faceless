"use client";

import * as React from "react";
import Link from "next/link";
import { Download, Film, Loader2, Plus, Trash2 } from "lucide-react";
import { AppMenu } from "@/components/app-menu";
import { Brand } from "@/components/brand";
import { CreditBadge } from "@/components/account/credit-badge";
import { ThemeToggle } from "@/components/theme-toggle";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { friendlyError } from "@/lib/errors";

type Project = {
  id: string;
  title: string | null;
  input_type: string | null;
  status: string;
  progress: string | null;
  error: string | null;
  result_url: string | null;
  created_at: string;
  updated_at: string;
};

const STATUS_VARIANT: Record<string, "default" | "accent" | "outline"> = {
  done: "accent",
  failed: "outline",
  processing: "default",
};

// Map a job's fine-grained pipeline stage to a short, human-readable label.
const STAGE_LABELS: Record<string, string> = {
  queued: "Queued",
  transcribing: "Transcribing narration",
  transcribed: "Awaiting setup",
  llm: "Planning visuals",
  llm_vocabulary: "Planning visuals",
  llm_beat_queries: "Planning visuals",
  clip_submit: "Finding clips",
  awaiting_clip: "Finding clips",
  vibe_pool_search: "Finding clips",
  ready: "Ready to render",
  render_queued: "Render queued",
  rendering: "Rendering video",
  done: "Done",
};

/** Friendly label for the badge given a project's status + job progress. */
function stageLabel(p: Project): string {
  if (p.status === "done") return "Done";
  if (p.status === "failed") return "Failed";
  if (p.progress && STAGE_LABELS[p.progress]) return STAGE_LABELS[p.progress];
  return "Processing";
}

// While any project is still working, refresh so stages update live.
const POLL_MS = 4000;
const isActive = (p: Project) => p.status !== "done" && p.status !== "failed";

export default function ProjectsPage() {
  const [projects, setProjects] = React.useState<Project[] | null>(null);
  const [confirmId, setConfirmId] = React.useState<string | null>(null);
  const [deletingId, setDeletingId] = React.useState<string | null>(null);

  React.useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | null = null;

    const tick = async () => {
      try {
        const res = await fetch("/api/projects", { cache: "no-store" });
        const data = res.ok ? await res.json() : { projects: [] };
        if (cancelled) return;
        const list: Project[] = data.projects ?? [];
        setProjects(list);
        // Keep polling only while something is still processing.
        if (list.some(isActive)) timer = setTimeout(tick, POLL_MS);
      } catch {
        if (!cancelled) setProjects((prev) => prev ?? []);
      }
    };

    void tick();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, []);

  const handleDelete = async (id: string) => {
    setDeletingId(id);
    try {
      const res = await fetch(`/api/projects/${id}`, { method: "DELETE" });
      if (res.ok) {
        setProjects((prev) => (prev ? prev.filter((p) => p.id !== id) : prev));
      }
    } finally {
      setDeletingId(null);
      setConfirmId(null);
    }
  };

  return (
    <main className="mx-auto max-w-4xl px-6 py-8">
      <header className="mb-8 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <AppMenu />
          <Link href="/" className="shrink-0">
            <Brand size="sm" />
          </Link>
        </div>
        <div className="flex items-center gap-2">
          <CreditBadge />
          <ThemeToggle />
          <Link href="/account" className="text-sm text-faint hover:text-cream">
            Account
          </Link>
        </div>
      </header>

      <div className="mb-6 flex items-center justify-between">
        <h1 className="font-heading text-3xl font-bold text-cream">Your projects</h1>
        <Button variant="primary" asChild>
          <Link href="/">
            <Plus className="size-4" />
            New video
          </Link>
        </Button>
      </div>

      {projects === null && <p className="text-faint">Loading…</p>}

      {projects !== null && projects.length === 0 && (
        <div className="panel flex flex-col items-center gap-3 p-12 text-center">
          <Film className="size-8 text-faint" />
          <p className="text-cream">No videos yet.</p>
          <p className="text-sm text-faint">Upload narration to create your first one.</p>
          <Button variant="primary" asChild className="mt-2">
            <Link href="/">
              <Plus className="size-4" />
              New video
            </Link>
          </Button>
        </div>
      )}

      {projects !== null && projects.length > 0 && (
        <ul className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          {projects.map((p) => (
            <li key={p.id} className="panel flex flex-col gap-3 p-4">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <p className="truncate font-medium text-cream">
                    {p.title || "Untitled video"}
                  </p>
                  <p className="text-xs text-faint">
                    {new Date(p.created_at).toLocaleString()}
                  </p>
                </div>
                <Badge variant={STATUS_VARIANT[p.status] ?? "default"}>
                  {stageLabel(p)}
                </Badge>
              </div>
              {p.status !== "failed" && isActive(p) && (
                <div className="flex items-center gap-2 text-xs text-faint">
                  <Loader2 className="size-3.5 animate-spin text-accent" />
                  <span>{stageLabel(p)}…</span>
                </div>
              )}
              {p.status === "failed" && (
                <p className="rounded-md bg-red-500/10 px-2.5 py-1.5 text-xs text-red-400">
                  {friendlyError(p.error, "Something broke while processing this video. Please try again.")}
                </p>
              )}
              {confirmId === p.id ? (
                <div className="flex items-center justify-between gap-2 rounded-md bg-red-500/10 px-2.5 py-2">
                  <span className="text-xs text-red-400">
                    Delete this project? This can&apos;t be undone.
                  </span>
                  <div className="flex shrink-0 items-center gap-1.5">
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => setConfirmId(null)}
                      disabled={deletingId === p.id}
                    >
                      Cancel
                    </Button>
                    <Button
                      variant="primary"
                      size="sm"
                      onClick={() => handleDelete(p.id)}
                      disabled={deletingId === p.id}
                    >
                      {deletingId === p.id ? (
                        <Loader2 className="size-4 animate-spin" />
                      ) : (
                        "Delete"
                      )}
                    </Button>
                  </div>
                </div>
              ) : (
                <div className="flex items-center gap-2">
                  <Button variant="secondary" size="sm" asChild>
                    <Link href={`/edit/${p.id}`}>Open</Link>
                  </Button>
                  {p.status === "done" && (
                    <Button variant="ghost" size="sm" asChild>
                      <a href={`/api/videos/${p.id}/download`}>
                        <Download className="size-4" />
                        Download
                      </a>
                    </Button>
                  )}
                  <Button
                    variant="ghost"
                    size="sm"
                    className="ml-auto text-faint hover:text-red-400"
                    onClick={() => setConfirmId(p.id)}
                    aria-label="Delete project"
                  >
                    <Trash2 className="size-4" />
                  </Button>
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
    </main>
  );
}
