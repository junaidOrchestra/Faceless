/** Resumable multipart upload to R2/S3 via presigned part URLs (browser → bucket). */

export type UploadedPart = {
  partNumber: number;
  etag: string;
};

// How many part PUTs run at once. A single stream rarely saturates the uplink
// and pays full round-trip latency per part; a small pool of parallel PUTs is
// the standard way to make multipart uploads fast without overwhelming the
// browser's per-host connection limit.
const PART_CONCURRENCY = 5;
// Per-part retry: one transient blip shouldn't fail a whole large upload.
const PART_MAX_ATTEMPTS = 4;
const PART_RETRY_BASE_MS = 600;

function sleep(ms: number): Promise<void> {
  return new Promise((r) => setTimeout(r, ms));
}

async function putPart(
  url: string,
  blob: Blob,
  signal?: AbortSignal,
): Promise<string> {
  let lastErr: unknown;
  for (let attempt = 1; attempt <= PART_MAX_ATTEMPTS; attempt += 1) {
    if (signal?.aborted) throw new DOMException("Aborted", "AbortError");
    try {
      const res = await fetch(url, { method: "PUT", body: blob, signal });
      if (!res.ok) {
        // 4xx (except 408/429) are not worth retrying — the URL/signature is bad.
        const retriable = res.status >= 500 || res.status === 408 || res.status === 429;
        if (!retriable) {
          throw new Error(`Part upload failed (${res.status}). Please try again.`);
        }
        throw new Error(`Part upload failed (${res.status})`);
      }
      const etag = res.headers.get("ETag") ?? res.headers.get("etag");
      if (!etag) {
        throw new Error("Part upload succeeded but no ETag was returned.");
      }
      return etag;
    } catch (e) {
      // A caller-triggered abort must propagate immediately (no retry).
      if (e instanceof DOMException && e.name === "AbortError") throw e;
      if (signal?.aborted) throw e;
      lastErr = e;
      if (attempt < PART_MAX_ATTEMPTS) {
        await sleep(PART_RETRY_BASE_MS * 2 ** (attempt - 1));
      }
    }
  }
  throw lastErr instanceof Error
    ? lastErr
    : new Error("Part upload failed after multiple attempts.");
}

/**
 * Upload a file in fixed-size chunks via a bounded pool of parallel PUTs,
 * returning part numbers + ETags (ordered) for finalize.
 */
export async function uploadFileMultipart(
  file: File,
  partUrls: { partNumber: number; url: string }[],
  partSizeBytes: number,
  onProgress?: (percent: number) => void,
  signal?: AbortSignal,
): Promise<UploadedPart[]> {
  const sorted = [...partUrls].sort((a, b) => a.partNumber - b.partNumber);
  const results: UploadedPart[] = new Array(sorted.length);
  let uploadedBytes = 0;
  let cursor = 0;

  const worker = async (): Promise<void> => {
    while (true) {
      if (signal?.aborted) throw new DOMException("Aborted", "AbortError");
      const i = cursor;
      cursor += 1;
      if (i >= sorted.length) return;

      const part = sorted[i];
      const start = (part.partNumber - 1) * partSizeBytes;
      const end = Math.min(start + partSizeBytes, file.size);
      const chunk = file.slice(start, end);
      const etag = await putPart(part.url, chunk, signal);
      results[i] = { partNumber: part.partNumber, etag };
      uploadedBytes += chunk.size;
      onProgress?.(Math.min(100, (uploadedBytes / file.size) * 100));
    }
  };

  const workers = Array.from(
    { length: Math.min(PART_CONCURRENCY, sorted.length) },
    () => worker(),
  );
  await Promise.all(workers);

  return results;
}
