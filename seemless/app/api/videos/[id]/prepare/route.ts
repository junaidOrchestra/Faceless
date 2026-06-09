import { NextResponse } from "next/server";
import { ORCH_TIMEOUT, orchFetch, upstreamErrorResponse } from "@/lib/server-config";

export const runtime = "nodejs";

// POST /api/videos/{id}/prepare -> orchestrator POST /videos/{id}/prepare
export async function POST(
  req: Request,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params;
  const body = await req.text();
  try {
    const res = await orchFetch(`/videos/${id}/prepare`, {
      method: "POST",
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
