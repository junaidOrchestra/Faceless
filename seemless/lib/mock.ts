import type { Asset, AssetSource, Beat, VideoJob, VisualType } from "./types";

// ---------------------------------------------------------------------------
// Mock data generator. Produces a believable storyboard so the editor is fully
// usable without the orchestrator running. Replace via lib/api.ts when wiring
// to the real backend.
// ---------------------------------------------------------------------------

// A short sample narration, already chunked into "beats" the way the
// orchestrator's whisper + segmentation stage would.
const SAMPLE_NARRATION: { text: string; visualType: VisualType; dur: number }[] = [
  { text: "Every great shipping route began as a gamble.", visualType: "symbolic", dur: 3.2 },
  { text: "Merchants loaded their fortunes onto wooden hulls.", visualType: "broll", dur: 3.6 },
  { text: "And pointed them toward a horizon they couldn't see.", visualType: "broll", dur: 3.4 },
  { text: "By the 1500s, spices were worth more than gold.", visualType: "archival", dur: 3.8 },
  { text: "A single ship could make a family rich for generations.", visualType: "broll", dur: 4.0 },
  { text: "But the ocean kept its own ledger.", visualType: "symbolic", dur: 2.8 },
  { text: "Storms, pirates, and disease took their cut.", visualType: "broll", dur: 3.2 },
  { text: "Routes snaked from Lisbon to the Spice Islands.", visualType: "map", dur: 3.6 },
  { text: "Each port a new set of rules and rivals.", visualType: "broll", dur: 3.0 },
  { text: "Three in four ships never returned.", visualType: "data", dur: 2.6 },
  { text: "So traders did something radical.", visualType: "symbolic", dur: 2.4 },
  { text: "They split the risk across many investors.", visualType: "broll", dur: 3.4 },
  { text: "A failed voyage no longer meant ruin.", visualType: "symbolic", dur: 3.0 },
  { text: "It was the seed of the modern corporation.", visualType: "archival", dur: 3.4 },
  { text: "Shares traded hands in Amsterdam's coffee houses.", visualType: "broll", dur: 3.8 },
  { text: "Prices rose and fell with every rumor from sea.", visualType: "data", dur: 3.6 },
  { text: "Maps became the most valuable documents on earth.", visualType: "map", dur: 3.4 },
  { text: "Whoever knew the route controlled the trade.", visualType: "symbolic", dur: 3.2 },
  { text: "Empires rose on the backs of these ledgers.", visualType: "broll", dur: 3.4 },
  { text: "And fell when the numbers stopped adding up.", visualType: "data", dur: 3.0 },
  { text: "A spice that grew on one island.", visualType: "broll", dur: 2.8 },
  { text: "Could reshape the politics of three continents.", visualType: "map", dur: 3.6 },
  { text: "The race wasn't just for wealth.", visualType: "symbolic", dur: 2.6 },
  { text: "It was for the future itself.", visualType: "symbolic", dur: 2.4 },
  { text: "New ships were faster, taller, hungrier.", visualType: "broll", dur: 3.2 },
  { text: "Crews of a hundred vanished into the blue.", visualType: "broll", dur: 3.4 },
  { text: "Their names survive only in faded logs.", visualType: "archival", dur: 3.2 },
  { text: "But the system they built never stopped.", visualType: "symbolic", dur: 3.0 },
  { text: "It just learned to move at the speed of light.", visualType: "broll", dur: 3.4 },
  { text: "Today a container leaves port every few seconds.", visualType: "data", dur: 3.6 },
  { text: "Carrying everything you'll ever own.", visualType: "broll", dur: 3.0 },
  { text: "The gamble never ended. It only got bigger.", visualType: "symbolic", dur: 3.6 },
];

const SOURCES: AssetSource[] = ["pexels", "wikimedia", "yours"];

/** Deterministic picsum thumbnail so mock images are stable across renders. */
function thumb(seed: string, w = 400, h = 400): string {
  return `https://picsum.photos/seed/${encodeURIComponent(seed)}/${w}/${h}`;
}

function makeCandidates(beatIndex: number, vt: VisualType): Asset[] {
  const count = 4 + (beatIndex % 3); // 4–6 options
  const kind: Asset["kind"] = vt === "broll" ? "video" : "photo";
  return Array.from({ length: count }, (_, i) => {
    // First two from pexels, then wikimedia; keeps a believable source mix.
    const source: AssetSource = i < 2 ? "pexels" : i < count - 1 ? "wikimedia" : "pexels";
    return {
      id: `b${beatIndex}-a${i}`,
      thumbUrl: thumb(`${beatIndex}-${i}`),
      source,
      kind,
    } satisfies Asset;
  });
}

/**
 * A fully-resolved mock job: every beat already has its candidates and a
 * pre-selected top pick. The time-based snapshot in lib/api.ts derives the
 * "transcribing" and "finding clips" phases from this base so the editor can
 * stream beats in like the real orchestrator pipeline.
 */
export function makeMockBase(id: string, fileName = "narration.mp3"): VideoJob {
  let cursor = 0;
  const beats: Beat[] = SAMPLE_NARRATION.map((b, index) => {
    const from = cursor;
    const to = cursor + b.dur;
    cursor = to;
    const candidates = b.visualType === "text_card" ? [] : makeCandidates(index, b.visualType);
    return {
      index,
      from,
      to,
      text: b.text,
      visualType: b.visualType,
      overlay: b.visualType === "text_card" ? b.text.slice(0, 60) : undefined,
      loading: false,
      included: true,
      // Pre-select the top candidate so the user reviews instead of starting blank.
      chosenAssetId: candidates.length === 0 ? null : candidates[0].id,
      candidates,
    } satisfies Beat;
  });

  return {
    id,
    status: "running",
    stage: "Picking clips",
    percent: 0,
    beats,
    aspect: "9:16",
    quality: "standard",
    captions: true,
    music: false,
    removeSilence: false,
    removeFillers: false,
    theme: { mode: "script" },
    fileName,
    durationSec: Math.round(cursor),
  };
}

// Beats that "stream in" later (still searching for clips) after transcription
// completes — the rest resolve immediately, mirroring the real clip stage.
export const MOCK_LOADING_BEATS = [3, 9, 15, 21, 27];

/** Mock search results appended in the picker's Search tab. */
export function makeSearchResults(beatIndex: number, query: string): Asset[] {
  const seedBase = `${query || "result"}-${beatIndex}-${Date.now()}`;
  return Array.from({ length: 6 }, (_, i) => ({
    id: `s-${beatIndex}-${Date.now()}-${i}`,
    thumbUrl: thumb(`${seedBase}-${i}`),
    source: SOURCES[i % 2] as AssetSource, // pexels / wikimedia
    kind: i % 2 === 0 ? "video" : "photo",
  }));
}
