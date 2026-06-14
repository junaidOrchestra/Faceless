import { NextResponse } from "next/server";
import { ORCH_TIMEOUT, orchFetch, upstreamErrorResponse } from "@/lib/server-config";

export const runtime = "nodejs";

// GET /api/jobs/{id} -> orchestrator GET /jobs/{id}
// Owner-scoped single-shot job progress (status/stage/percent/result_url).
export async function GET(
  _req: Request,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params;
  try {
    const res = await orchFetch(`/jobs/${id}`, {
      cache: "no-store",
      timeoutMs: ORCH_TIMEOUT.status,
    });
    const data = await res.json().catch(() => ({}));
    return NextResponse.json(data, { status: res.status });
  } catch (e) {
    return upstreamErrorResponse(e);
  }
}
