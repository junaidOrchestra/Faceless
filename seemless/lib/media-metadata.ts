/** Best-effort client-side duration probe (seconds) before upload. */

export async function probeMediaDuration(file: File): Promise<number> {
  const url = URL.createObjectURL(file);
  try {
    const isVideo = file.type.startsWith("video/") || /\.(mp4|webm|mov|mkv)$/i.test(file.name);
    const el = document.createElement(isVideo ? "video" : "audio");
    el.preload = "metadata";
    el.muted = true;
    return await new Promise<number>((resolve, reject) => {
      const cleanup = () => {
        el.removeAttribute("src");
        el.load();
        URL.revokeObjectURL(url);
      };
      el.onloadedmetadata = () => {
        const d = el.duration;
        cleanup();
        if (!Number.isFinite(d) || d <= 0) {
          reject(new Error("Could not read the media duration."));
          return;
        }
        resolve(d);
      };
      el.onerror = () => {
        cleanup();
        reject(new Error("Could not read the media duration."));
      };
      el.src = url;
    });
  } catch (e) {
    URL.revokeObjectURL(url);
    throw e;
  }
}
