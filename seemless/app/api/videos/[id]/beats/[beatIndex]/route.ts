import { NextResponse } from "next/server";
import { ORCH_TIMEOUT, orchFetch, upstreamErrorResponse } from "@/lib/server-config";

export const runtime = "nodejs";

// DELETE /api/videos/{id}/beats/{beatIndex} ->
//   orchestrator DELETE /videos/{id}/beats/{beatIndex}
// Removes a user-added text-card / effect insert. Beat indices shift.
export async function DELETE(
  _req: Request,
  { params }: { params: Promise<{ id: string; beatIndex: string }> },
) {
  const { id, beatIndex } = await params;
  try {
    const res = await orchFetch(`/videos/${id}/beats/${beatIndex}`, {
      method: "DELETE",
      timeoutMs: ORCH_TIMEOUT.mutate,
    });
    const data = await res.json().catch(() => ({}));
    return NextResponse.json(data, { status: res.status });
  } catch (e) {
    return upstreamErrorResponse(e);
  }
}
