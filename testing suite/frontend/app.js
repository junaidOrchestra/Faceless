"use strict";

// The UI talks only to its own origin; nginx proxies /api -> backend.
const API = "/api";

let CONFIG = { vibes: [], formats: [], qualities: [] };
const downloaded = new Set(); // job ids already auto-downloaded
let pollTimer = null;

// Per-job beats inspector state (survives the 2s polling re-render).
const beatsOpen = new Set(); // job ids whose beats panel is expanded
const beatsCache = new Map(); // job id -> { loading, error, beats, summary }
let lastBatch = null; // most recent batch payload, for re-rendering on demand

const $ = (sel, root = document) => root.querySelector(sel);
const el = (tag, cls, text) => {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text != null) n.textContent = text;
  return n;
};

// ---- selects ---------------------------------------------------------------

function contentSelect(value = "script") {
  const s = el("select", "theme");
  s.appendChild(new Option("Match content (script)", "script"));
  const og = el("optgroup");
  og.label = "Vibe";
  CONFIG.vibes.forEach((v) => og.appendChild(new Option(v.label, v.id)));
  s.appendChild(og);
  s.value = value;
  return s;
}

function fromOptions(cls, items, value) {
  const s = el("select", cls);
  items.forEach((i) => s.appendChild(new Option(i.label, i.id)));
  if (value) s.value = value;
  return s;
}

// ---- rows ------------------------------------------------------------------

function defaults() {
  return {
    content: $("#defTheme").value,
    format: $("#defFormat").value,
    quality: $("#defQuality").value,
    subtitles: $("#defSubtitles").checked,
  };
}

function addRow(opts = {}) {
  const d = defaults();
  const row = el("div", "row");

  if (opts.uploadId) {
    // Upload row: show the filename instead of a URL field.
    row.dataset.uploadId = opts.uploadId;
    const name = el("div", "url filename");
    name.title = opts.filename || "audio file";
    name.appendChild(el("span", "file-tag", "FILE"));
    name.appendChild(document.createTextNode(" " + (opts.filename || "audio file")));
    row.appendChild(name);
  } else {
    const urlInput = el("input", "url");
    urlInput.type = "text";
    urlInput.placeholder = "https://www.youtube.com/watch?v=…";
    urlInput.value = opts.url || "";
    row.appendChild(urlInput);
  }

  const remove = el("button", "remove", "✕");
  remove.type = "button";
  remove.title = "Remove";
  remove.onclick = () => row.remove();

  const optsEl = el("div", "row-opts");
  optsEl.appendChild(contentSelect(d.content));
  optsEl.appendChild(fromOptions("format", CONFIG.formats, d.format));
  optsEl.appendChild(fromOptions("quality", CONFIG.qualities, d.quality));
  const subLabel = el("label", "check");
  const sub = el("input");
  sub.type = "checkbox";
  sub.className = "subtitles";
  sub.checked = d.subtitles;
  subLabel.appendChild(sub);
  subLabel.appendChild(document.createTextNode("Subs"));
  optsEl.appendChild(subLabel);

  row.append(remove, optsEl);
  $("#rows").appendChild(row);
}

function collectRows() {
  return [...document.querySelectorAll(".row")]
    .map((row) => {
      const content = $(".theme", row).value;
      const base = {
        theme_mode: content === "script" ? "script" : "vibe",
        vibe: content === "script" ? null : content,
        video_format: $(".format", row).value,
        quality: $(".quality", row).value,
        subtitles: $(".subtitles", row).checked,
      };
      if (row.dataset.uploadId) {
        return { upload_id: row.dataset.uploadId, ...base };
      }
      const url = $(".url", row).value.trim();
      if (!url) return null;
      return { url, ...base };
    })
    .filter(Boolean);
}

// ---- rendering results -----------------------------------------------------

function fmtDur(s) {
  if (s == null) return "—";
  if (s < 60) return `${s.toFixed(1)}s`;
  const m = Math.floor(s / 60);
  return `${m}m ${Math.round(s % 60)}s`;
}

function stepRow(step) {
  const row = el("div", `step ${step.status}`);
  row.appendChild(el("span", "dot"));
  const label = el("span", "step-label");
  label.appendChild(document.createTextNode(step.label));
  if (step.detail) {
    const sm = el("small", null, step.detail);
    label.appendChild(sm);
  }
  row.appendChild(label);
  row.appendChild(el("span", "step-time", step.duration_s != null ? fmtDur(step.duration_s) : ""));
  return row;
}

function jobCard(job) {
  const card = el("div", "job");
  card.id = `job-${job.id}`;

  const head = el("div", "job-head");
  const left = el("div");
  left.appendChild(el("p", "job-title", job.title || "Fetching…"));
  left.appendChild(el("p", "job-url", job.source || job.url || ""));
  const metaBits = [];
  if (job.beats != null) metaBits.push(`${job.beats} beats`);
  if (job.duration_s) metaBits.push(`${Math.round(job.duration_s)}s source`);
  if (job.output_size_bytes) metaBits.push(`${(job.output_size_bytes / 1048576).toFixed(1)} MB`);
  if (metaBits.length) left.appendChild(el("p", "job-meta", metaBits.join(" · ")));
  head.appendChild(left);
  head.appendChild(el("span", `badge ${job.status}`, job.status));
  card.appendChild(head);

  const steps = el("div", "steps");
  job.steps.forEach((s) => steps.appendChild(stepRow(s)));
  card.appendChild(steps);

  const total = el("div", "job-total");
  total.appendChild(el("span", "total-time", `Total: ${fmtDur(job.total_duration_s)}`));
  if (job.has_video) {
    const dl = el("a", "dl", "⬇ Download video");
    dl.href = `${API}/jobs/${job.id}/video`;
    dl.setAttribute("download", "");
    total.appendChild(dl);
  }
  // Beats inspector toggle — available once the clip search has produced beats.
  const beatsReady = (job.beats || 0) > 0;
  if (beatsReady) {
    const toggle = el(
      "button",
      "ghost beats-toggle",
      `${beatsOpen.has(job.id) ? "▾" : "▸"} Beats & keywords`,
    );
    toggle.type = "button";
    toggle.onclick = () => toggleBeats(job.id);
    total.appendChild(toggle);
  }

  card.appendChild(total);

  if (beatsReady && beatsOpen.has(job.id)) {
    card.appendChild(beatsSection(job.id));
  }

  if (job.error) card.appendChild(el("div", "err", `Error: ${job.error}`));

  if (job.logs && job.logs.length) {
    const details = el("details", "logs");
    details.appendChild(el("summary", null, "Logs"));
    details.appendChild(document.createTextNode(job.logs.join("\n")));
    card.appendChild(details);
  }

  return card;
}

// ---- beats inspector -------------------------------------------------------

const TYPE_CLASS = { personality: "t-person", event: "t-event", general: "t-general" };

function chip(text, cls) {
  return el("span", `chip ${cls || ""}`.trim(), text);
}

function beatsSection(jobId) {
  const wrap = el("div", "beats");
  const cache = beatsCache.get(jobId);

  if (!cache || cache.loading) {
    wrap.appendChild(el("p", "beats-empty", "Loading beats…"));
    return wrap;
  }
  if (cache.error) {
    wrap.appendChild(el("p", "beats-empty err", cache.error));
    return wrap;
  }
  if (!cache.beats.length) {
    wrap.appendChild(el("p", "beats-empty", "No beats available yet."));
    return wrap;
  }

  if (cache.summary) {
    const sum = el("div", "beats-summary");
    sum.appendChild(chip(`${cache.summary.personality || 0} personality`, "t-person"));
    sum.appendChild(chip(`${cache.summary.event || 0} event`, "t-event"));
    sum.appendChild(chip(`${cache.summary.general || 0} general`, "t-general"));
    wrap.appendChild(sum);
  }

  cache.beats.forEach((b) => {
    const row = el("div", "beat");

    const top = el("div", "beat-top");
    top.appendChild(el("span", "beat-idx", `#${b.index}`));
    top.appendChild(chip(b.type_label, TYPE_CLASS[b.type_bucket]));
    if (b.prefers_video) top.appendChild(chip("video", "t-vid"));
    const t = el("span", "beat-time");
    if (b.start_s != null && b.end_s != null) {
      t.textContent = `${b.start_s.toFixed(1)}–${b.end_s.toFixed(1)}s`;
    }
    top.appendChild(t);
    row.appendChild(top);

    row.appendChild(el("p", "beat-text", b.text));

    const kw = el("div", "beat-kw");
    kw.appendChild(el("span", "beat-kw-label", "Keywords"));
    if (b.keywords.length) {
      b.keywords.forEach((k) => kw.appendChild(chip(k, "kw")));
    } else {
      kw.appendChild(el("span", "beats-empty", b.theme ? `vibe: ${b.theme}` : "—"));
    }
    row.appendChild(kw);

    const src = el("div", "beat-src");
    src.appendChild(el("span", "beat-kw-label", "→ Sources"));
    (b.sources || []).forEach((s) => src.appendChild(chip(s, "src")));
    row.appendChild(src);

    wrap.appendChild(row);
  });

  return wrap;
}

async function fetchBeats(jobId) {
  try {
    const res = await fetch(`${API}/jobs/${jobId}/beats`);
    if (!res.ok) throw new Error(await res.text());
    const data = await res.json();
    beatsCache.set(jobId, {
      loading: false,
      beats: data.beats || [],
      summary: data.summary,
    });
  } catch (e) {
    beatsCache.set(jobId, { loading: false, error: `Failed to load beats: ${e.message}`, beats: [] });
  }
}

async function toggleBeats(jobId) {
  if (beatsOpen.has(jobId)) {
    beatsOpen.delete(jobId);
    rerender();
    return;
  }
  beatsOpen.add(jobId);
  if (!beatsCache.get(jobId)) beatsCache.set(jobId, { loading: true, beats: [] });
  rerender();
  await fetchBeats(jobId);
  rerender();
}

function rerender() {
  if (lastBatch) renderBatch(lastBatch);
}

function renderBatch(batch) {
  lastBatch = batch;
  $("#emptyState").hidden = batch.jobs.length > 0;
  $("#batchStats").textContent = batch.jobs.length
    ? `${batch.done} done · ${batch.failed} failed · ${batch.in_progress} running`
    : "";

  const jobsEl = $("#jobs");
  jobsEl.innerHTML = "";
  batch.jobs.forEach((job) => {
    jobsEl.appendChild(jobCard(job));
    if (job.status === "done" && job.has_video && $("#autoDownload").checked && !downloaded.has(job.id)) {
      downloaded.add(job.id);
      const a = el("a");
      a.href = `${API}/jobs/${job.id}/video`;
      a.download = "";
      document.body.appendChild(a);
      a.click();
      a.remove();
    }
  });

  return batch.in_progress === 0 && batch.total > 0;
}

// ---- uploads ---------------------------------------------------------------

async function handleFiles(fileList) {
  const files = [...fileList];
  if (!files.length) return;
  const btn = $("#uploadBtn");
  const prev = btn.textContent;
  btn.disabled = true;
  btn.textContent = "Uploading…";
  try {
    const form = new FormData();
    files.forEach((f) => form.append("files", f));
    const res = await fetch(`${API}/uploads`, { method: "POST", body: form });
    if (!res.ok) throw new Error(await res.text());
    const data = await res.json();
    data.uploads.forEach((u) => addRow({ uploadId: u.upload_id, filename: u.filename }));
  } catch (e) {
    alert(`Upload failed: ${e.message}`);
  } finally {
    btn.disabled = false;
    btn.textContent = prev;
  }
}

// ---- run -------------------------------------------------------------------

async function run() {
  const videos = collectRows();
  if (!videos.length) {
    alert("Add at least one YouTube URL.");
    return;
  }
  const btn = $("#runBtn");
  btn.disabled = true;
  btn.textContent = "Starting…";

  try {
    const res = await fetch(`${API}/batches`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ videos }),
    });
    if (!res.ok) throw new Error(await res.text());
    const batch = await res.json();
    downloaded.clear();
    startPolling(batch.id);
    renderBatch(batch);
  } catch (e) {
    alert(`Failed to start: ${e.message}`);
  } finally {
    btn.disabled = false;
    btn.textContent = "Run pipeline";
  }
}

function startPolling(batchId) {
  if (pollTimer) clearInterval(pollTimer);
  const tick = async () => {
    try {
      const res = await fetch(`${API}/batches/${batchId}`);
      if (!res.ok) return;
      const batch = await res.json();
      const finished = renderBatch(batch);
      // Keep any open beats panel fresh for jobs that are still working.
      for (const job of batch.jobs) {
        if (beatsOpen.has(job.id) && job.status === "running") {
          fetchBeats(job.id).then(() => {
            if (beatsOpen.has(job.id)) rerender();
          });
        }
      }
      if (finished) {
        clearInterval(pollTimer);
        pollTimer = null;
      }
    } catch {
      /* transient; keep polling */
    }
  };
  tick();
  pollTimer = setInterval(tick, 2000);
}

// ---- init ------------------------------------------------------------------

async function init() {
  try {
    const res = await fetch(`${API}/config`);
    CONFIG = await res.json();
    $("#orchInfo").textContent = CONFIG.orchestrator_url || "orchestrator";
  } catch {
    $("#orchInfo").textContent = "backend unreachable";
  }

  // Populate defaults panel.
  const defTheme = contentSelect("script");
  defTheme.id = "defThemeSel";
  $("#defTheme").replaceWith(defTheme);
  defTheme.id = "defTheme";

  const defFormat = fromOptions("", CONFIG.formats, "youtube");
  defFormat.id = "defFormat";
  $("#defFormat").replaceWith(defFormat);

  const defQuality = fromOptions("", CONFIG.qualities, "hd");
  defQuality.id = "defQuality";
  $("#defQuality").replaceWith(defQuality);

  $("#addRowBtn").onclick = () => addRow();
  $("#uploadBtn").onclick = () => $("#fileInput").click();
  $("#fileInput").onchange = (e) => {
    handleFiles(e.target.files);
    e.target.value = ""; // allow re-selecting the same file
  };
  $("#runBtn").onclick = run;

  addRow();
}

document.addEventListener("DOMContentLoaded", init);
