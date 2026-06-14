"use client";

/**
 * Durable browser-local cache of the uploaded media File, keyed by job id.
 *
 * The editor previews/edits against the EXACT uploaded file (not the cloud copy).
 * An in-memory object URL is lost on refresh, and browsers can't reopen an
 * arbitrary disk path for security reasons — so we persist the file's bytes in
 * IndexedDB. On reload the editor rehydrates a fresh object URL from here, so the
 * local preview keeps working across refreshes, dev restarts, and direct visits.
 *
 * Entries are pruned to the most recent few jobs to bound disk usage (uploads can
 * be hundreds of MB each).
 */

const DB_NAME = "brollio-media";
const STORE = "uploads";
const DB_VERSION = 1;
const MAX_ENTRIES = 3;

type MediaRecord = {
  jobId: string;
  blob: Blob;
  name: string;
  type: string;
  ts: number;
};

function idbAvailable(): boolean {
  return typeof window !== "undefined" && "indexedDB" in window;
}

function openDb(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, DB_VERSION);
    req.onupgradeneeded = () => {
      const db = req.result;
      if (!db.objectStoreNames.contains(STORE)) {
        const store = db.createObjectStore(STORE, { keyPath: "jobId" });
        store.createIndex("ts", "ts");
      }
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

function tx<T>(
  db: IDBDatabase,
  mode: IDBTransactionMode,
  run: (store: IDBObjectStore) => IDBRequest<T>,
): Promise<T> {
  return new Promise((resolve, reject) => {
    const t = db.transaction(STORE, mode);
    const store = t.objectStore(STORE);
    const req = run(store);
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

/** Persist (or replace) the uploaded file for a job. Best-effort; never throws. */
export async function persistUploadedMedia(jobId: string, file: File): Promise<void> {
  if (!idbAvailable()) return;
  try {
    const db = await openDb();
    const record: MediaRecord = {
      jobId,
      blob: file,
      name: file.name,
      type: file.type,
      ts: Date.now(),
    };
    await tx(db, "readwrite", (s) => s.put(record));
    await prune(db);
    db.close();
  } catch (e) {
    console.warn(`[media-cache] persist failed for ${jobId}`, e);
  }
}

/** Return the persisted file for a job (or null). */
export async function loadUploadedMedia(jobId: string): Promise<File | null> {
  if (!idbAvailable()) return null;
  try {
    const db = await openDb();
    const rec = await tx<MediaRecord | undefined>(db, "readonly", (s) => s.get(jobId));
    db.close();
    if (!rec) return null;
    return new File([rec.blob], rec.name || "upload", { type: rec.type || rec.blob.type });
  } catch (e) {
    console.warn(`[media-cache] load failed for ${jobId}`, e);
    return null;
  }
}

/** Delete a job's persisted file (e.g. after a successful render). */
export async function deleteUploadedMedia(jobId: string): Promise<void> {
  if (!idbAvailable()) return;
  try {
    const db = await openDb();
    await tx(db, "readwrite", (s) => s.delete(jobId));
    db.close();
  } catch (e) {
    console.warn(`[media-cache] delete failed for ${jobId}`, e);
  }
}

/** Keep only the most recent ``MAX_ENTRIES`` jobs to bound disk usage. */
async function prune(db: IDBDatabase): Promise<void> {
  try {
    const keys = await new Promise<{ jobId: string; ts: number }[]>((resolve, reject) => {
      const t = db.transaction(STORE, "readonly");
      const store = t.objectStore(STORE);
      const out: { jobId: string; ts: number }[] = [];
      const cursorReq = store.openCursor();
      cursorReq.onsuccess = () => {
        const cursor = cursorReq.result;
        if (cursor) {
          const v = cursor.value as MediaRecord;
          out.push({ jobId: v.jobId, ts: v.ts });
          cursor.continue();
        } else {
          resolve(out);
        }
      };
      cursorReq.onerror = () => reject(cursorReq.error);
    });
    if (keys.length <= MAX_ENTRIES) return;
    const stale = keys.sort((a, b) => b.ts - a.ts).slice(MAX_ENTRIES);
    await new Promise<void>((resolve) => {
      const t = db.transaction(STORE, "readwrite");
      const store = t.objectStore(STORE);
      for (const k of stale) store.delete(k.jobId);
      t.oncomplete = () => resolve();
      t.onerror = () => resolve();
    });
  } catch (e) {
    console.warn("[media-cache] prune failed", e);
  }
}
