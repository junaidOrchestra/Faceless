import { NextResponse } from "next/server";
import { ORCH_TIMEOUT, orchFetch, upstreamErrorResponse } from "@/lib/server-config";

export const runtime = "nodejs";

// POST /api/videos/{id}/beats/{beatIndex}/merge ->
//   orchestrator POST /videos/{id}/beats/{beatIndex}/merge
// Merges a beat with the next one (video projects). Beat indices shift.
export async function POST(
  _req: Request,
  { params }: { params: Promise<{ id: string; beatIndex: string }> },
) {
  const { id, beatIndex } = await params;
  try {
    const res = await orchFetch(`/videos/${id}/beats/${beatIndex}/merge`, {
      method: "POST",
      timeoutMs: ORCH_TIMEOUT.mutate,
    });
    const data = await res.json().catch(() => ({}));
    return NextResponse.json(data, { status: res.status });
  } catch (e) {
    return upstreamErrorResponse(e);
  }
}
