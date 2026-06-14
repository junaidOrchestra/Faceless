"use client";

/**
 * Attach a remote media URL to a <video> element.
 *
 * The editing proxy is a faststart progressive MP4 today (dense keyframes for
 * instant seek). When an HLS playlist is available later (``.m3u8``), hls.js
 * takes over automatically.
 */

import Hls from "hls.js";

function isHlsUrl(url: string): boolean {
  return /\.m3u8(\?|$)/i.test(url);
}

export function attachMediaSource(
  video: HTMLVideoElement,
  url: string | null | undefined,
): () => void {
  if (!url) {
    video.removeAttribute("src");
    video.load();
    return () => {};
  }

  if (isHlsUrl(url)) {
    if (Hls.isSupported()) {
      const hls = new Hls({
        enableWorker: true,
        lowLatencyMode: false,
        maxBufferLength: 30,
      });
      hls.loadSource(url);
      hls.attachMedia(video);
      return () => {
        hls.destroy();
        video.removeAttribute("src");
        video.load();
      };
    }
    if (video.canPlayType("application/vnd.apple.mpegurl")) {
      video.src = url;
      return () => {
        video.removeAttribute("src");
        video.load();
      };
    }
  }

  video.src = url;
  return () => {
    video.removeAttribute("src");
    video.load();
  };
}

/** Seek helper that waits for metadata when the element isn't ready yet. */
export function seekVideo(video: HTMLVideoElement, timeS: number): void {
  const t = Math.max(0, timeS);
  const apply = () => {
    try {
      if (Math.abs(video.currentTime - t) > 0.04) video.currentTime = t;
    } catch {
      // not seekable yet
    }
  };
  if (video.readyState >= 1) apply();
  else {
    const onMeta = () => {
      video.removeEventListener("loadedmetadata", onMeta);
      apply();
    };
    video.addEventListener("loadedmetadata", onMeta);
  }
}
