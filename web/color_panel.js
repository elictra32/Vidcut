// Colour correction of the selected clip (too yellow, too dark, flat...). The preview shows it live; export applies the
// same correction (core/grade.py). Intro/outro clips can be corrected too.
import { getProject, subscribe, ui, update } from "./state.js";
import { applyGrade, isNeutral, NEUTRAL } from "./grade.js";
import { flush } from "./state.js";
import * as player from "./player.js";
import { $, basename, el, numberSlider, recall, remember } from "./util.js";

const FIELDS = [
  ["temperature", "Warmth", "Left = cooler / less yellow, right = warmer"],
  ["tint", "Tint", "Left = greener, right = more magenta"],
  ["brightness", "Brightness", ""],
  ["contrast", "Contrast", ""],
  ["saturation", "Colour strength", "Left = paler, right = more vivid"],
];
const PRESETS = [
  ["Less yellow", { temperature: -35, tint: 5 }],
  ["Cooler", { temperature: -20 }],
  ["Warmer", { temperature: 20 }],
  ["Punchier", { contrast: 15, saturation: 20 }],
  ["Brighter", { brightness: 15, contrast: 5 }],
];

const videos = () => [document.getElementById("video"), document.getElementById("video2")];
const current = () => getProject()?.clips.find((c) => c.id === ui.currentClipId) ?? null;

function refreshPreview() {
  const p = getProject();
  for (const v of videos()) applyGrade(v, p?.clips.find((c) => c.id === v._clipId));
}

// ---- exact preview: the picture the export will really produce, drawn by the same pipeline --------------------------
// A <video> with a CSS filter can only approximate what ffmpeg does, so while a colour correction is active and the video
// is paused, the preview shows a real rendered frame of the playhead instead (subtitles and images are in it already).
const frameBox = $("#frame");
const exactImg = el("img", { id: "exact-frame", alt: "Exact preview of the exported picture" });
frameBox.append(exactImg);
let exactOn = recall("vidcut.exactPreview", "1") === "1";
let exactSeq = 0, exactTimer = null, exactKey = "", exactUrl = null;
const exactNote = el("span", { class: "muted small", id: "exact-note" });

function hideExact() {
  exactSeq++;
  frameBox.classList.remove("exact", "stale");
  exactKey = "";
}

function scheduleExact() {
  clearTimeout(exactTimer);
  const p = getProject();
  const clip = p?.clips.find((c) => c.id === player.getLoadedClipId());
  if (!exactOn || !clip || (clip.role ?? "main") !== "main" || isNeutral(clip.grade) || player.isPlaying()) {
    hideExact();
    exactNote.textContent = "";
    return;
  }
  const key = JSON.stringify([clip.grade, Math.round(player.getTime() * 20), p.preset, p.clips.length]);
  if (key === exactKey) return;
  if (frameBox.classList.contains("exact")) frameBox.classList.add("stale"); // the old picture no longer matches the sliders
  exactTimer = setTimeout(async () => {
    const seq = ++exactSeq;
    exactNote.textContent = "Rendering the real picture…";
    try {
      if (!(await flush())) return;
      const res = await fetch("/api/preview-frame", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ t: player.getTime() }) });
      if (!res.ok || seq !== exactSeq) { if (seq === exactSeq) exactNote.textContent = ""; return; }
      const url = URL.createObjectURL(await res.blob());
      if (seq !== exactSeq) return URL.revokeObjectURL(url);
      exactImg.src = url;
      if (exactUrl) URL.revokeObjectURL(exactUrl);
      exactUrl = url;
      exactKey = key;
      frameBox.classList.add("exact");
      frameBox.classList.remove("stale");
      exactNote.textContent = "Showing the exact exported picture (paused). Press Play for the live preview.";
    } catch {
      if (seq === exactSeq) exactNote.textContent = "";
    }
  }, 300);
}

export function initColorPanel() {
  const root = $("#color-panel");
  const sliders = {};
  const exactBox = el("input", { type: "checkbox", id: "exact-preview", checked: exactOn });
  exactBox.addEventListener("change", () => { exactOn = exactBox.checked; remember("vidcut.exactPreview", exactOn ? "1" : "0"); exactKey = ""; scheduleExact(); });

  const setGrade = (patch, why = "grade") => update((p) => {
    const c = p.clips.find((x) => x.id === ui.currentClipId);
    if (c) c.grade = { ...NEUTRAL, ...c.grade, ...patch };
  }, why);

  const render = () => {
    const c = current();
    if (!c) return root.replaceChildren(el("h2", {}, "Colour"), el("p", { class: "muted small" }, "Select a clip first."));
    const g = { ...NEUTRAL, ...c.grade };
    const rows = FIELDS.map(([key, label, tip]) => {
      const ns = numberSlider({ min: -100, max: 100, step: 1, value: g[key], label: `${label} (-100 to 100)`, onInput: (v) => setGrade({ [key]: v }) });
      sliders[key] = ns;
      if (tip) ns.root.title = tip;
      return el("div", { class: "field" }, el("span", {}, label), ns.root);
    });
    root.replaceChildren(
      el("h2", {}, "Colour"),
      el("p", { class: "muted small" }, `Applies to: ${basename(c.path)}. The preview is close to the export, not identical; use "Check real frame" in Export for the exact picture.`),
      el("label", { class: "row small" }, exactBox, el("span", {}, "Exact preview: show the real exported colours while paused")),
      exactNote,
      el("div", { class: "row wrap" }, PRESETS.map(([name, patch]) => el("button", { class: "small", "data-preset": name, onclick: () => setGrade({ ...NEUTRAL, ...patch }, "grade-preset") }, name))),
      ...rows,
      el("div", { class: "row" },
        el("button", { id: "btn-grade-reset", class: "ghost small", disabled: isNeutral(c.grade), onclick: () => setGrade({ ...NEUTRAL }, "grade-preset") }, "Reset this clip"),
        el("button", { id: "btn-grade-all", class: "ghost small", title: "Give every clip the same correction", onclick: () => update((p) => {
          const cur = p.clips.find((x) => x.id === ui.currentClipId);
          for (const x of p.clips) x.grade = { ...NEUTRAL, ...cur.grade };
        }, "grade-preset") }, "Use on all clips")));
  };

  player.onTime(scheduleExact); // moving the playhead, or starting/stopping playback
  subscribe((why) => {
    scheduleExact();
    refreshPreview();
    // dragging a slider only changes the picture; the sliders themselves are rebuilt when the clip or the whole state changes
    if (["load", "clip", "undo", "grade-preset"].includes(why)) render();
  });
  render();
  refreshPreview();
}
