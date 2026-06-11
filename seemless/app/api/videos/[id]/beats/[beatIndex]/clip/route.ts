import { NextResponse } from "next/server";
import { ORCH_TIMEOUT, orchFetch, upstreamErrorResponse } from "@/lib/server-config";

export const runtime = "nodejs";

// POST /api/videos/{id}/beats/{beatIndex}/clip ->
//   orchestrator POST /videos/{id}/beats/{beatIndex}/clip
// Forwards the recorded animated-text-card clip (multipart) so the backend can
// store it and register it as the beat's selected candidate.
export async function POST(
  req: Request,
  { params }: { params: Promise<{ id: string; beatIndex: string }> },
) {
  const { id, beatIndex } = await params;
  const form = await req.formData();
  try {
    const res = await orchFetch(`/videos/${id}/beats/${beatIndex}/clip`, {
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
