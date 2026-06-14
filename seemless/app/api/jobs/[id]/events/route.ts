import {
  ORCHESTRATOR_URL,
  orchHeaders,
  upstreamErrorResponse,
} from "@/lib/server-config";

export const runtime = "nodejs";
// Never cache or statically optimize a live event stream.
export const dynamic = "force-dynamic";

// GET /api/jobs/{id}/events -> orchestrator GET /jobs/{id}/events (SSE)
//
// The browser EventSource can't attach the Supabase bearer, so this same-origin
// proxy injects it server-side and pipes the orchestrator's text/event-stream
// body straight through. The client's abort signal is forwarded upstream so a
// closed tab tears down the backend stream instead of leaking a connection.
export async function GET(
  req: Request,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params;
  try {
    const upstream = await fetch(`${ORCHESTRATOR_URL}/jobs/${id}/events`, {
      headers: await orchHeaders({ Accept: "text/event-stream" }),
      cache: "no-store",
      signal: req.signal,
    });

    // Surface auth/ownership/404 errors as JSON rather than a broken stream.
    if (!upstream.ok || !upstream.body) {
      const text = await upstream.text().catch(() => "");
      return new Response(text || JSON.stringify({ error: "stream unavailable" }), {
        status: upstream.status || 502,
        headers: { "Content-Type": "application/json" },
      });
    }

    return new Response(upstream.body, {
      status: 200,
      headers: {
        "Content-Type": "text/event-stream; charset=utf-8",
        "Cache-Control": "no-cache, no-transform",
        Connection: "keep-alive",
        "X-Accel-Buffering": "no",
      },
    });
  } catch (e) {
    return upstreamErrorResponse(e);
  }
}
