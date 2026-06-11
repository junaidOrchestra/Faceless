/**
 * User-facing error sanitization.
 *
 * Backend/pipeline failures often carry raw, leaky details — upstream URLs, HTTP
 * status codes, library names, stack-ish text. Those must never reach the user:
 * they're confusing and expose internals (e.g. the clip-server host). This maps
 * any such message to a calm, reassuring generic one.
 *
 * Actionable messages the user CAN fix (tier limits, insufficient credits, quota
 * caps) don't contain these markers, so they pass through unchanged.
 */

// Hallmarks of an internal/technical error we should hide.
const TECHNICAL_MARKERS: RegExp[] = [
  /https?:\/\//i, // any URL (e.g. the clip-server host, MDN status link)
  /\bserver error\b/i,
  /\binternal server error\b/i,
  /\bstatus\b[^]*?\/\d{3}/i, // ".../Status/500"
  /\btraceback\b|\bexception\b|stack ?trace/i,
  /\bhttpx\b|\bpsycopg\b|\bsqlalchemy\b|\basyncio\b|\bredis\b/i,
  /clip[- ]?server/i,
  /no media source|fell back to text|required api key|sources=/i,
  /timed ?out|unreachable|\bdeadline\b|could not persist|nonetype/i,
];

const DEFAULT_GENERIC =
  "Something broke on our end. We've been notified and we're already on it — please try again in a moment.";

/**
 * Return a safe, friendly message for display.
 *
 * @param raw      The raw error string from the backend (may be empty/leaky).
 * @param fallback Message to show when `raw` is empty or judged technical.
 */
export function friendlyError(
  raw?: string | null,
  fallback: string = DEFAULT_GENERIC,
): string {
  const text = (raw ?? "").trim();
  if (!text) return fallback;
  if (TECHNICAL_MARKERS.some((re) => re.test(text))) return fallback;
  // Anything suspiciously long is almost certainly a dump, not a crafted note.
  if (text.length > 240) return fallback;
  return text;
}
