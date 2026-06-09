import { NextResponse } from "next/server";
import { ORCH_TIMEOUT, orchFetch, upstreamErrorResponse } from "@/lib/server-config";

export const runtime = "nodejs";

// GET /api/videos/{id}/beats -> orchestrator GET /videos/{id}/beats
export async function GET(
  _req: Request,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params;
  try {
    const res = await orchFetch(`/videos/${id}/beats`, {
      cache: "no-store",
      timeoutMs: ORCH_TIMEOUT.beats,
    });
    const data = await res.json().catch(() => ({ beats: [] }));
    return NextResponse.json(data, { status: res.status });
  } catch (e) {
    return upstreamErrorResponse(e, { beats: [] });
  }
}
