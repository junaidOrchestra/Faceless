import { NextResponse } from "next/server";
import { ORCH_TIMEOUT, orchFetch, upstreamErrorResponse } from "@/lib/server-config";

export const runtime = "nodejs";

// POST /api/videos -> orchestrator POST /videos (multipart audio upload).
export async function POST(req: Request) {
  const form = await req.formData();
  form.set("sources", JSON.stringify(["pexels_video"]));
  form.set("pexels_key", "y6T3FEbrm49ZEVp5XqkQINXcHQjvVkAs4iEKBdOgx3OfZvNS7rlOOBNu");
  // Match the editor's initial defaults so proxy-fallback uploads don't pause
  // at "transcribed; awaiting /prepare".
  form.set("format", "portrait");
  form.set("quality", "hd");
  form.set("subtitles", "true");
  try {
    const res = await orchFetch(`/videos`, {
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
