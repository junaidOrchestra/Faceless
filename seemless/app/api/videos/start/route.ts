import { NextResponse } from "next/server";
import { ORCH_TIMEOUT, orchFetch, upstreamErrorResponse } from "@/lib/server-config";

export const runtime = "nodejs";

// POST /api/videos/start -> orchestrator POST /videos/start
export async function POST(req: Request) {
  const raw = await req.json().catch(() => ({}));
  const body = {
    ...raw,
    sources: raw.sources ?? ["pexels_video"],
    pexels_key:
      raw.pexels_key ?? "y6T3FEbrm49ZEVp5XqkQINXcHQjvVkAs4iEKBdOgx3OfZvNS7rlOOBNu",
  };
  try {
    const res = await orchFetch(`/videos/start`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      timeoutMs: ORCH_TIMEOUT.mutate,
    });
    const data = await res.json().catch(() => ({}));
    return NextResponse.json(data, { status: res.status });
  } catch (e) {
    return upstreamErrorResponse(e);
  }
}
