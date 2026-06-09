import { NextResponse } from "next/server";
import { ORCH_TIMEOUT, orchFetch, upstreamErrorResponse } from "@/lib/server-config";

export const runtime = "nodejs";

// GET /api/projects -> orchestrator GET /projects (caller's projects only).
export async function GET() {
  try {
    const res = await orchFetch(`/projects`, {
      cache: "no-store",
      timeoutMs: ORCH_TIMEOUT.status,
    });
    const data = await res.json().catch(() => ({}));
    return NextResponse.json(data, { status: res.status });
  } catch (e) {
    return upstreamErrorResponse(e, { projects: [] });
  }
}
