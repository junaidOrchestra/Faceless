import { ORCH_TIMEOUT, isAbortError, orchFetch } from "@/lib/server-config";

export const runtime = "nodejs";

// GET /api/videos/{id}/download -> proxy the finished MP4 (or redirect to B2).
export async function GET(
  _req: Request,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params;
  let res: Response;
  try {
    res = await orchFetch(`/videos/${id}/download`, {
      redirect: "follow",
      cache: "no-store",
      timeoutMs: ORCH_TIMEOUT.streamTtfb,
    });
  } catch (e) {
    return new Response("Video temporarily unavailable.", {
      status: isAbortError(e) ? 504 : 502,
    });
  }
  if (!res.ok || !res.body) {
    return new Response("Video not available.", { status: res.status || 502 });
  }
  return new Response(res.body, {
    status: 200,
    headers: {
      "Content-Type": res.headers.get("Content-Type") ?? "video/mp4",
      "Content-Disposition": `attachment; filename="${id}.mp4"`,
    },
  });
}
