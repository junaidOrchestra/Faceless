import { ORCH_TIMEOUT, isAbortError, orchFetch } from "@/lib/server-config";

export const runtime = "nodejs";

// POST /api/videos/transcribe-audio -> store a client-extracted WAV for Whisper.
export async function POST(req: Request) {
  let form: FormData;
  try {
    form = await req.formData();
  } catch {
    return new Response("Invalid form data.", { status: 400 });
  }

  const videoJobId = String(form.get("video_job_id") ?? "").trim();
  const audio = form.get("audio");
  if (!videoJobId || !(audio instanceof Blob)) {
    return new Response("video_job_id and audio are required.", { status: 400 });
  }

  const upstream = new FormData();
  upstream.append("video_job_id", videoJobId);
  upstream.append("audio", audio, "transcribe.wav");

  let res: Response;
  try {
    res = await orchFetch("/videos/transcribe-audio", {
      method: "POST",
      body: upstream,
      timeoutMs: ORCH_TIMEOUT.upload,
    });
  } catch (e) {
    return new Response("Transcription audio temporarily unavailable.", {
      status: isAbortError(e) ? 504 : 502,
    });
  }

  if (!res.ok) {
    const detail = await res.text().catch(() => "");
    console.warn(`[transcribe-audio] upstream ${res.status}: ${detail}`);
    return new Response(detail || "Could not store transcription audio.", {
      status: res.status,
    });
  }

  return new Response(await res.text(), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}
