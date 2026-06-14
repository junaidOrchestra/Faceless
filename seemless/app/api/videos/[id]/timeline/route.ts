import { NextResponse } from "next/server";
import { ORCH_TIMEOUT, orchFetch, upstreamErrorResponse } from "@/lib/server-config";

export const runtime = "nodejs";

// PATCH /api/videos/{id}/timeline -> orchestrator PATCH /videos/{id}/timeline
// Debounced flush of metadata-only editor mutations (exclusions, selections,
// transitions). No media is touched until export.
export async function PATCH(
  req: Request,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params;
  const body = await req.text();
  try {
    const res = await orchFetch(`/videos/${id}/timeline`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body,
      timeoutMs: ORCH_TIMEOUT.mutate,
    });
    const data = await res.json().catch(() => ({}));
    return NextResponse.json(data, { status: res.status });
  } catch (e) {
    return upstreamErrorResponse(e);
  }
}
