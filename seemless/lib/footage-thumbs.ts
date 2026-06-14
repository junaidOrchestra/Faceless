import type { FootageThumbnails } from "./types";

export type SpriteCrop = {
  url: string;
  /** Negative offsets for `background-position` (px). */
  x: number;
  y: number;
  /** Tile size (px) — set as the element's clip box / background sizing. */
  w: number;
  h: number;
  /** Full sheet size (px) for `background-size`. */
  sheetW: number;
  sheetH: number;
};

/**
 * Resolve the sprite crop for a given timestamp (seconds). Returns null when the
 * index is missing/empty so callers can fall back to a video frame.
 */
export function spriteCropForTime(
  thumbs: FootageThumbnails | undefined,
  t: number,
): SpriteCrop | null {
  if (!thumbs || !thumbs.sheetUrls.length || thumbs.count <= 0) return null;
  const perSheet = Math.max(1, thumbs.cols * thumbs.rows);
  const idx = Math.min(
    thumbs.count - 1,
    Math.max(0, Math.round((t || 0) / Math.max(0.001, thumbs.intervalS))),
  );
  const sheet = Math.min(thumbs.sheetUrls.length - 1, Math.floor(idx / perSheet));
  const within = idx - sheet * perSheet;
  const col = within % thumbs.cols;
  const row = Math.floor(within / thumbs.cols);
  return {
    url: thumbs.sheetUrls[sheet],
    x: -(col * thumbs.thumbW),
    y: -(row * thumbs.thumbH),
    w: thumbs.thumbW,
    h: thumbs.thumbH,
    sheetW: thumbs.cols * thumbs.thumbW,
    sheetH: thumbs.rows * thumbs.thumbH,
  };
}
