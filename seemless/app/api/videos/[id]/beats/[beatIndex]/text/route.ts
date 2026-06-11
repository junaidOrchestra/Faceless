import { NextResponse } from "next/server";
import { ORCH_TIMEOUT, orchFetch, upstreamErrorResponse } from "@/lib/server-config";

export const runtime = "nodejs";

// PATCH /api/videos/{id}/beats/{beatIndex}/text ->
//   orchestrator PATCH /videos/{id}/beats/{beatIndex}/text
// Forwards a transcription typo fix: only the beat's caption text changes.
export async function PATCH(
  req: Request,
  { params }: { params: Promise<{ id: string; beatIndex: string }> },
) {
  const { id, beatIndex } = await params;
  const body = await req.text();
  try {
    const res = await orchFetch(`/videos/${id}/beats/${beatIndex}/text`, {
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
