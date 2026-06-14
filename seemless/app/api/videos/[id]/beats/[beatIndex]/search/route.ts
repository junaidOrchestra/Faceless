import { NextResponse } from "next/server";
import { ORCH_TIMEOUT, orchFetch, upstreamErrorResponse } from "@/lib/server-config";

export const runtime = "nodejs";

// POST /api/videos/{id}/beats/{beatIndex}/search ->
//   orchestrator POST /videos/{id}/beats/{beatIndex}/search
// Kicks off an on-demand stock clip search for a single beat (footage stays the
// default; fetched stock are merged in as alternates).
export async function POST(
  _req: Request,
  { params }: { params: Promise<{ id: string; beatIndex: string }> },
) {
  const { id, beatIndex } = await params;
  try {
    const res = await orchFetch(`/videos/${id}/beats/${beatIndex}/search`, {
      method: "POST",
      timeoutMs: ORCH_TIMEOUT.mutate,
    });
    const data = await res.json().catch(() => ({}));
    return NextResponse.json(data, { status: res.status });
  } catch (e) {
    return upstreamErrorResponse(e);
  }
}
