"use client";

const audioUrls = new Map<string, string>();

export function rememberPreviewAudio(jobId: string, file: File): string {
  const previous = audioUrls.get(jobId);
  if (previous) URL.revokeObjectURL(previous);

  const url = URL.createObjectURL(file);
  audioUrls.set(jobId, url);

  return url;
}

export function getPreviewAudioUrl(jobId: string): string | undefined {
  return audioUrls.get(jobId);
}

export function forgetPreviewAudio(jobId: string): void {
  const url = audioUrls.get(jobId);
  if (url) URL.revokeObjectURL(url);
  audioUrls.delete(jobId);
}
