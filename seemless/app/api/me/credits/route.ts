import { NextResponse } from "next/server";
import { ORCH_TIMEOUT, orchFetch, upstreamErrorResponse } from "@/lib/server-config";

export const runtime = "nodejs";

// GET /api/me/credits -> orchestrator GET /me/credits (balance + ledger).
export async function GET() {
  try {
    const res = await orchFetch(`/me/credits`, {
      cache: "no-store",
      timeoutMs: ORCH_TIMEOUT.status,
    });
    const data = await res.json().catch(() => ({}));
    return NextResponse.json(data, { status: res.status });
  } catch (e) {
    return upstreamErrorResponse(e);
  }
}
