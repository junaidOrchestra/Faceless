import { NextResponse } from "next/server";
import { ORCH_TIMEOUT, orchFetch, upstreamErrorResponse } from "@/lib/server-config";

export const runtime = "nodejs";

// POST /api/videos/{id}/render -> orchestrator POST /videos/{id}/render
// Forwards an optional JSON body ({ overrides: { beatIndex: candidateIndex } })
// so the editor's clip swaps are applied to the render.
export async function POST(
  req: Request,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params;
  const bodyText = await req.text();
  try {
    const res = await orchFetch(`/videos/${id}/render`, {
      method: "POST",
      headers: bodyText ? { "Content-Type": "application/json" } : undefined,
      body: bodyText || undefined,
      timeoutMs: ORCH_TIMEOUT.mutate,
    });
    const data = await res.json().catch(() => ({}));
    return NextResponse.json(data, { status: res.status });
  } catch (e) {
    return upstreamErrorResponse(e);
  }
}
