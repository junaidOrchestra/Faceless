// Client-side media loading for the effect recorder. Remote stock footage and
// posters are routed through the same-origin /api/media-proxy so they can be
// drawn onto a <canvas> without tainting it (cross-origin pixels otherwise block
// captureStream/toBlob). All loaders resolve to something with a `draw(ctx,w,h)`
// that cover-fits the source — the recorder calls it each frame.

/** Wrap an absolute URL so it streams through our origin (untainted canvas). */
export function mediaProxyUrl(url: string): string {
  return `/api/media-proxy?url=${encodeURIComponent(url)}`;
}

/** Cover-fit drawable: fills (w,h) preserving aspect, centred (like CSS cover). */
export type Drawable = {
  draw: (ctx: CanvasRenderingContext2D, w: number, h: number) => void;
  /** Optional teardown (stop/scrub a backing <video>). */
  dispose?: () => void;
};

function drawCover(
  ctx: CanvasRenderingContext2D,
  src: CanvasImageSource,
  sw: number,
  sh: number,
  w: number,
  h: number,
): void {
  if (!sw || !sh) {
    ctx.fillStyle = "#000";
    ctx.fillRect(0, 0, w, h);
    return;
  }
  const scale = Math.max(w / sw, h / sh);
  const dw = sw * scale;
  const dh = sh * scale;
  ctx.fillStyle = "#000";
  ctx.fillRect(0, 0, w, h);
  ctx.drawImage(src, (w - dw) / 2, (h - dh) / 2, dw, dh);
}

/**
 * Load a remote overlay clip as a muted, looping, playing <video> ready to be
 * drawn each frame. Resolves as soon as the FIRST frame is available
 * (`loadeddata`) rather than waiting for the whole file — the effect only
 * records ~0.3s, and the proxy streams via HTTP Range, so only the leading
 * fragment of the clip is actually fetched.
 */
export async function loadOverlayVideo(url: string): Promise<Drawable & { el: HTMLVideoElement }> {
  const video = document.createElement("video");
  video.src = mediaProxyUrl(url);
  video.muted = true;
  video.loop = true;
  video.playsInline = true;
  video.crossOrigin = "anonymous";
  // "metadata" lets the browser fetch just enough to render the first frame and
  // stream the rest on demand, instead of eagerly buffering the entire clip.
  video.preload = "metadata";
  await new Promise<void>((resolve, reject) => {
    const onReady = () => resolve();
    video.addEventListener("loadeddata", onReady, { once: true });
    video.addEventListener("error", () => reject(new Error("overlay load failed")), { once: true });
    setTimeout(() => reject(new Error("overlay load timed out")), 12_000);
  });
  await video.play().catch(() => {});
  return {
    el: video,
    draw: (ctx, w, h) => drawCover(ctx, video, video.videoWidth, video.videoHeight, w, h),
    dispose: () => {
      try {
        video.pause();
        video.removeAttribute("src");
        video.load();
      } catch {
        /* ignore */
      }
    },
  };
}

/** Load a still image (poster / photo) as a cover-fit drawable. */
export async function loadImageDrawable(url: string): Promise<Drawable> {
  const img = new Image();
  img.crossOrigin = "anonymous";
  img.src = mediaProxyUrl(url);
  await new Promise<void>((resolve, reject) => {
    img.onload = () => resolve();
    img.onerror = () => reject(new Error("image load failed"));
    setTimeout(() => reject(new Error("image load timed out")), 15_000);
  });
  return {
    draw: (ctx, w, h) => drawCover(ctx, img, img.naturalWidth, img.naturalHeight, w, h),
  };
}

/**
 * Load a single frame of a remote video (seeked to `atS`) as a frozen drawable —
 * used to "freeze" the previous beat's frame behind a sound-only insert.
 */
export async function loadVideoFrameDrawable(url: string, atS: number): Promise<Drawable> {
  const video = document.createElement("video");
  video.src = mediaProxyUrl(url);
  video.muted = true;
  video.playsInline = true;
  video.crossOrigin = "anonymous";
  video.preload = "auto";
  await new Promise<void>((resolve, reject) => {
    video.addEventListener("loadeddata", () => resolve(), { once: true });
    video.addEventListener("error", () => reject(new Error("frame video load failed")), { once: true });
    setTimeout(() => reject(new Error("frame video load timed out")), 15_000);
  });
  const target = Math.max(0, Math.min(atS, (video.duration || atS) - 0.05));
  await new Promise<void>((resolve) => {
    const onSeeked = () => resolve();
    video.addEventListener("seeked", onSeeked, { once: true });
    try {
      video.currentTime = target;
    } catch {
      resolve();
    }
    setTimeout(resolve, 4_000);
  });
  return {
    draw: (ctx, w, h) => drawCover(ctx, video, video.videoWidth, video.videoHeight, w, h),
    dispose: () => {
      try {
        video.removeAttribute("src");
        video.load();
      } catch {
        /* ignore */
      }
    },
  };
}

/** A neutral dark drawable (no media available — sound plays over a soft frame). */
export function neutralDrawable(): Drawable {
  return {
    draw: (ctx, w, h) => {
      const g = ctx.createRadialGradient(w / 2, h / 2, 0, w / 2, h / 2, Math.max(w, h) * 0.7);
      g.addColorStop(0, "#1a1a20");
      g.addColorStop(1, "#0a0a0d");
      ctx.fillStyle = g;
      ctx.fillRect(0, 0, w, h);
    },
  };
}
