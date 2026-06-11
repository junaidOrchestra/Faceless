import { NextResponse } from "next/server";
import { ORCH_TIMEOUT, orchFetch, upstreamErrorResponse } from "@/lib/server-config";

export const runtime = "nodejs";

// POST /api/videos/{id}/beats/insert ->
//   orchestrator POST /videos/{id}/beats/insert
// Forwards a recorded standalone animated-text-card clip plus its insertion
// metadata. The backend stores it, shifts later beats, and inserts a silent gap
// into the render audio at the same timeline position.
export async function POST(
  req: Request,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params;
  const form = await req.formData();
  try {
    const res = await orchFetch(`/videos/${id}/beats/insert`, {
      method: "POST",
      body: form,
      timeoutMs: ORCH_TIMEOUT.upload,
    });
    const data = await res.json().catch(() => ({}));
    return NextResponse.json(data, { status: res.status });
  } catch (e) {
    return upstreamErrorResponse(e);
  }
}
