import { NextResponse } from "next/server";
import { ORCH_TIMEOUT, orchFetch, upstreamErrorResponse } from "@/lib/server-config";

export const runtime = "nodejs";

// POST /api/videos/{id}/beats/{beatIndex}/candidate ->
//   orchestrator POST /videos/{id}/beats/{beatIndex}/candidate
// Persists a clip chosen from the free-text "Search" tab as the beat's selected
// candidate so the render uses it.
export async function POST(
  req: Request,
  { params }: { params: Promise<{ id: string; beatIndex: string }> },
) {
  const { id, beatIndex } = await params;
  const body = await req.text();
  try {
    const res = await orchFetch(`/videos/${id}/beats/${beatIndex}/candidate`, {
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
