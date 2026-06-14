import { NextResponse } from "next/server";
import { ORCH_TIMEOUT, orchFetch, upstreamErrorResponse } from "@/lib/server-config";

export const runtime = "nodejs";

// PATCH /api/videos/{id}/beats/{beatIndex}/timeline ->
//   orchestrator PATCH /videos/{id}/beats/{beatIndex}/timeline
// Persists a beat's footage trim (source_in_s / source_out_s) and/or trailing
// transition. Mutates only the timeline JSON — no media is touched until export.
export async function PATCH(
  req: Request,
  { params }: { params: Promise<{ id: string; beatIndex: string }> },
) {
  const { id, beatIndex } = await params;
  const body = await req.text();
  try {
    const res = await orchFetch(`/videos/${id}/beats/${beatIndex}/timeline`, {
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
