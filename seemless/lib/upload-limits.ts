/** Product-wide upload caps (mirrors orchestrator config). */

export const MAX_UPLOAD_BYTES = 3 * 1024 * 1024 * 1024;
export const MAX_UPLOAD_DURATION_S = 3600;
export const MAX_UPLOAD_GB = 3;
export const MAX_UPLOAD_MINUTES = 60;

export function formatUploadLimits(): string {
  return `up to ${MAX_UPLOAD_MINUTES} min · max ${MAX_UPLOAD_GB} GB`;
}
