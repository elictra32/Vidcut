import { api, ApiError } from "./api.js";
import { addToQueue } from "./queue_panel.js";
import { flush, getPresets, getProject, saveFailed, setUi, subscribe, ui, update, withSavedProject } from "./state.js";
import { trackJob } from "./status.js";
import { showError } from "./toast.js";
import * as tm from "./timeline_math.js";
import * as player from "./player.js";
import { $, el, fmtTime } from "./util.js";

const LABELS = { tiktok: "TikTok 9:16", youtube: "YouTube 16:9" };
const currentClip = () => {
  const p = getProject();
  return p?.clips.find((c) => c.id === (player.getLoadedClipId() ?? ui.currentClipId)) ?? null;
};

function setPreset(key) {
  update((p) => {
    p.preset = key;
    Object.assign(p.style, getPresets()[key].style_overrides); // each preset has its own subtitle size/position
  }, "preset");
}

async function checkFrame() {
  try {
    if (!(await flush())) throw saveFailed();
    const res = await fetch("/api/preview-frame", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ t: player.getTime() }) });
    if (!res.ok) {
      const d = await res.json().catch(() => null);
      throw new ApiError(d?.error ?? { message: `HTTP ${res.status}` }, res.status);
    }
    const url = URL.createObjectURL(await res.blob());
    const dlg = el("dialog", { class: "frame-dialog" },
      el("p", { class: "muted small" }, "This image comes from the real export pipeline (framing + subtitles at the playhead)"),
      el("img", { src: url, alt: "Sample frame from the file to be exported" }),
      el("button", { class: "primary", onclick: () => dlg.close() }, "Close"));
    dlg.addEventListener("close", () => (URL.revokeObjectURL(url), dlg.remove()));
    document.body.append(dlg);
    dlg.showModal();
  } catch (e) {
    showError(e);
  }
}

export function initExportPanel() {
  const root = $("#export-panel");
  const result = el("div", { class: "export-result" });
  const framing = el("div", {});
  const seg = el("div", { class: "seg", role: "group", "aria-label": "Choose platform" });
  const safe = el("input", { type: "checkbox", checked: true });
  safe.addEventListener("change", () => setUi({ showSafeZone: safe.checked }, "safezone"));
  const exportBtn = el("button", { class: "primary" }, "Export video");

  // ---- file format, quality / target size, folder, and a size estimate ----
  const setExport = (patch) => update((p) => Object.assign(p.export, patch), "export");
  const option = (value, label) => el("option", { value }, label);
  const container = el("select", { id: "opt-container" },
    option("mp4", "MP4 (plays everywhere, recommended)"), option("mov", "MOV"), option("mkv", "MKV"), option("webm", "WebM (slower to encode)"));
  const quality = el("select", { id: "opt-quality" },
    option("auto", "Best value (keeps the look, smallest file)"), option("high", "High quality (large file)"), option("medium", "Medium quality"), option("small", "Small file"), option("custom", "Custom size"));
  const target = el("input", { type: "number", id: "opt-target", min: 1, step: 1 });
  const targetRow = el("label", { class: "field" }, el("span", {}, "Target file size (MB)"), target);
  const folderText = el("span", { class: "folder-text small" });
  const estimate = el("p", { id: "estimate", class: "estimate small" });
  container.addEventListener("change", () => setExport({ container: container.value }));
  quality.addEventListener("change", () => setExport({ quality: quality.value, ...(quality.value === "custom" && !getProject().export.target_mb ? { target_mb: 20 } : {}) }));
  target.addEventListener("input", () => setExport({ target_mb: parseFloat(target.value) || null }));
  const setFolder = async (call) => {
    try {
      const r = await call();
      update((p) => (p.export.out_dir = r.out_dir), "export");
    } catch (e) {
      showError(e);
    }
  };
  const folderRow = el("div", { class: "field" }, el("span", {}, "Save to"), folderText,
    el("div", { class: "row" },
      el("button", { id: "opt-folder-pick", onclick: () => setFolder(() => api("POST", "/api/export-folder/pick")) }, "Choose folder…"),
      el("button", { class: "ghost", onclick: () => setFolder(() => api("POST", "/api/export-folder", { path: "" })) }, "Use default folder")));

  let lastSig = "", estimateSeq = 0, estimateTimer = null;
  const extrasSeconds = (p, role) => p.clips.filter((c) => c.role === role)
    .reduce((t, c) => t + tm.enabledKeeps(c).reduce((a, k) => a + k.end - k.start, 0), 0);
  const refreshEstimate = () => {
    const p = getProject();
    if (!p) return;
    const sig = JSON.stringify([p.selection, p.preset, p.export.container, p.export.quality, p.export.target_mb,
      p.clips.map((c) => [c.id, c.role, c.keeps])]);
    if (sig === lastSig) return;
    lastSig = sig;
    clearTimeout(estimateTimer);
    estimateTimer = setTimeout(async () => {
      const seq = ++estimateSeq;
      try {
        if (!(await flush())) return; // the server estimates from its saved copy
        const r = await api("POST", "/api/export/estimate");
        if (seq !== estimateSeq) return;
        const mb = r.bytes / 1048576;
        const parts = [extrasSeconds(p, "intro") && `Intro ${fmtTime(extrasSeconds(p, "intro"))}`, `Content ${fmtTime(p.selection ? p.selection.end - p.selection.start : tm.editedDuration(p.clips))}`,
          extrasSeconds(p, "outro") && `Outro ${fmtTime(extrasSeconds(p, "outro"))}`].filter(Boolean).join(" + ");
        estimate.textContent = `Length ${fmtTime(r.seconds)} (${parts}) · ${r.upper_bound ? "up to" : "approx."} size ${mb >= 100 ? mb.toFixed(0) : mb.toFixed(1)} MB (±15%) · video ${(r.video_kbps / 1000).toFixed(1)} Mbps`;
      } catch (e) {
        if (seq === estimateSeq) estimate.textContent = e.payload?.code === "selection_invalid" ? "Can't estimate size: the selection is invalid" : "";
      }
    }, 350);
  };

  exportBtn.addEventListener("click", async () => {
    const p = getProject();
    const total = tm.editedDuration(p.clips);
    if (!total) return showError({ payload: { message: "Nothing to export", hint: "Add a clip or re-enable some cut sections" } });
    if (!p.selection && !confirm(`No In/Out selected, so the whole timeline (${fmtTime(total)}) will be exported, which may take a long time. Continue?`)) return;
    exportBtn.disabled = true;
    result.replaceChildren();
    try {
      const { job } = await withSavedProject(() => api("POST", "/api/export", { preset: p.preset }));
      const done = await trackJob("Exporting video", job);
      if (!done) return;
      const { video, srt, dir, downloadable } = done.result;
      const link = (name, label) => el("a", { href: `/exports/${encodeURIComponent(name)}`, download: name }, label);
      result.replaceChildren(el("strong", {}, "Export finished"),
        downloadable ? el("div", { class: "row" }, link(video, `Download .${video.split(".").pop()}`), link(srt, "Download .srt")) : "",
        el("p", { class: "muted small" }, `File ${video} is in folder: ${dir}`));
    } catch (e) {
      showError(e);
    } finally {
      exportBtn.disabled = false;
    }
  });

  root.replaceChildren(el("h2", {}, "Export"), seg, framing,
    el("label", { class: "field" }, el("span", {}, "File type"), container),
    el("label", { class: "field" }, el("span", {}, "Quality / size"), quality), targetRow, folderRow, estimate,
    el("label", { class: "field inline" }, el("span", {}, "Show app UI safe zone"), safe),
    el("div", { class: "row" }, el("button", { onclick: checkFrame }, "Check real frame"), exportBtn,
      el("button", { id: "btn-queue-export", title: "Add this export to the queue instead of running it now", onclick: () => addToQueue("export") }, "Add to queue")), result);

  const render = () => {
    const p = getProject();
    const presets = getPresets();
    if (!p || !Object.keys(presets).length) return;
    container.value = p.export.container;
    quality.value = p.export.quality;
    targetRow.hidden = p.export.quality !== "custom";
    if (document.activeElement !== target) target.value = p.export.target_mb ?? "";
    folderText.textContent = p.export.out_dir || "App default folder (VidcutProjects\\default\\exports)";
    refreshEstimate();
    seg.replaceChildren(...Object.keys(presets).map((k) =>
      el("button", { "aria-pressed": String(p.preset === k), onclick: () => p.preset !== k && setPreset(k) }, LABELS[k] ?? k)));
    const clip = currentClip();
    const pr = presets[p.preset];
    framing.replaceChildren();
    if (!clip) return;
    if (Math.abs(clip.width / clip.height - pr.width / pr.height) < 0.01) {
      framing.append(el("p", { class: "muted small" }, "The clip's aspect ratio already matches this preset; no framing needed"));
      return;
    }
    const setMode = (mode) => update(() => (clip.framing.mode = mode), "framing");
    const radio = (mode, label) => {
      const r = el("input", { type: "radio", name: "framing", checked: clip.framing.mode === mode });
      r.addEventListener("change", () => setMode(mode));
      return el("label", { class: "field inline" }, r, el("span", {}, label));
    };
    framing.append(el("h3", {}, "Framing for this clip"),
      radio("blur_fit", "Full frame + blurred background"), radio("crop", "Crop to fill"));
    if (clip.framing.mode === "crop" && clip.width / clip.height > pr.width / pr.height) {
      const s = el("input", { type: "range", min: 0, max: 1, step: 0.01, value: clip.framing.crop_center_x });
      s.addEventListener("input", () => update(() => (clip.framing.crop_center_x = parseFloat(s.value)), "framing-x"));
      framing.append(el("label", { class: "field" }, el("span", {}, "Part of the image to keep (left–right)"), s),
        el("p", { class: "muted small" }, "Or drag on the preview to move the frame"));
    }
  };
  // "framing-x" fires while dragging the slider; re-rendering then would drop the slider mid-drag
  subscribe((why) => !why.startsWith("ov-") && why !== "framing-x" && why !== "subs-text" && why !== "subs-pos" && why !== "subs" && why !== "select" && render());
}
