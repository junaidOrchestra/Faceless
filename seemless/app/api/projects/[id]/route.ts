import { NextResponse } from "next/server";
import { ORCH_TIMEOUT, orchFetch, upstreamErrorResponse } from "@/lib/server-config";

export const runtime = "nodejs";

// GET /api/projects/{id} -> orchestrator GET /projects/{id} (404 if not owner).
export async function GET(
  _req: Request,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params;
  try {
    const res = await orchFetch(`/projects/${id}`, {
      cache: "no-store",
      timeoutMs: ORCH_TIMEOUT.status,
    });
    const data = await res.json().catch(() => ({}));
    return NextResponse.json(data, { status: res.status });
  } catch (e) {
    return upstreamErrorResponse(e);
  }
}

// DELETE /api/projects/{id} -> orchestrator DELETE /projects/{id} (owner-scoped).
export async function DELETE(
  _req: Request,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params;
  try {
    const res = await orchFetch(`/projects/${id}`, {
      method: "DELETE",
      cache: "no-store",
      timeoutMs: ORCH_TIMEOUT.mutate,
    });
    if (res.status === 204) {
      return new NextResponse(null, { status: 204 });
    }
    const data = await res.json().catch(() => ({}));
    return NextResponse.json(data, { status: res.status });
  } catch (e) {
    return upstreamErrorResponse(e);
  }
}
