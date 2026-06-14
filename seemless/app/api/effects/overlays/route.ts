import { NextResponse } from "next/server";
import { ORCH_TIMEOUT, orchFetch, upstreamErrorResponse } from "@/lib/server-config";

export const runtime = "nodejs";

// GET /api/effects/overlays -> orchestrator GET /effects/overlays
// Curated, pre-fetched transition/overlay clips grouped by visual category, so
// the effect dialog can drop in real footage without a live clip search.
export async function GET() {
  try {
    const res = await orchFetch(`/effects/overlays`, {
      method: "GET",
      timeoutMs: ORCH_TIMEOUT.beats,
    });
    const data = await res.json().catch(() => ({}));
    return NextResponse.json(data, { status: res.status });
  } catch (e) {
    return upstreamErrorResponse(e);
  }
}
