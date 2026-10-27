// Subtitle panel (auto-generate, list, edit text), and the subtitle lane on the edit timeline.
import { api } from "./api.js";
import { getProject, loadProject, reloadAfterJob, setSelectedSub, subscribe, ui, update, withSavedProject } from "./state.js";
import { trackJob } from "./status.js";
import { showError, showToast } from "./toast.js";
import * as tm from "./timeline_math.js";
import * as player from "./player.js";
import { LANE_TOP, setSubtitleLane, timeAtX } from "./timeline_view.js";
import { $, basename, cssVar, el, fmtTime, numberSlider, recall, remember } from "./util.js";

const MODELS = {
  "large-v3": "Most accurate · first use downloads about 3 GB · slowest on CPU",
  medium: "Balanced · first use downloads about 1.5 GB",
  small: "Fastest · about 500 MB download · less accurate",
};
const spanOf = (s) => tm.subtitleEditedSpan(getProject().clips, s);

async function generate(model) {
  const p = getProject();
  if (!p.selection) return showToast("Set the range first (Set In / Set Out buttons) so only that range is transcribed", "error", 6000);
  if (p.subtitles.length && !confirm("Existing subtitles will be replaced by the new ones. Continue?")) return;
  try {
    const { job } = await withSavedProject(() => api("POST", "/api/transcribe", { model })); // the server uses its saved copy
    const done = await trackJob("Transcribing (can take several minutes on CPU)", job);
    if (!done) return;
    await reloadAfterJob();
    if (done.result.empty) showToast("No speech found in the selection. Try another range, or click “+ Add subtitle” to type one", "error", 7000);
    else showToast(`Created ${done.result.count} subtitle lines`);
  } catch (e) {
    showError(e);
  }
}

/** Import an .srt (e.g. YouTube auto captions). Times are source times of the SAME uncut video. */
function openImportDialog(fileName, srtText) {
  const p = getProject();
  if (!p.clips.length) return showToast("Add a clip first, then import subtitles", "error");
  const clipSel = el("select", {}, p.clips.map((c) => el("option", { value: c.id }, basename(c.path))));
  clipSel.value = p.clips.some((c) => c.id === ui.currentClipId) ? ui.currentClipId : p.clips[0].id;
  const onlySel = el("input", { type: "checkbox", checked: !!p.selection, disabled: !p.selection });
  const offset = el("input", { type: "number", value: 0, step: 0.1 });
  // The captions may belong to the ORIGINAL video while this clip is its cut version: map the times through the cuts.
  let pieces = null;
  const mode = el("select", { id: "srt-mode" },
    el("option", { value: "same" }, "Made for this exact video"),
    el("option", { value: "cut" }, "Made for the video BEFORE dead air was cut (this clip is the cut version)"));
  const cutStatus = el("p", { class: "muted small", id: "srt-cut-status" });
  const pickOriginal = el("button", { id: "btn-pick-original", onclick: async () => {
    try {
      const { path } = await api("POST", "/api/pick-original");
      if (!path) return;
      const { job } = await withSavedProject(() => api("POST", `/api/clips/${clipSel.value}/align`, { original_path: path }));
      const done = await trackJob("Matching the sound to the original", job);
      if (!done) return;
      pieces = done.result.pieces;
      cutStatus.textContent = `Matched ${Math.round(done.result.coverage * 100)}% of this video to the original (${pieces.length} part${pieces.length === 1 ? "" : "s"}).`;
    } catch (e) { showError(e); }
  } }, "Choose the original video…");
  const cutBox = el("div", { class: "field", hidden: true }, cutStatus, pickOriginal);
  const lookForManifest = async () => {
    pieces = null;
    cutStatus.textContent = "Looking for a Vidcut cut file next to this video…";
    pickOriginal.hidden = false;
    try {
      const m = await api("GET", `/api/clips/${clipSel.value}/cut-manifest`);
      if (m.found) {
        pieces = m.sources[0].pieces;
        cutStatus.textContent = `Found the Vidcut cut file next to this video (source: ${m.sources[0].name}). Times will be mapped exactly.`;
        pickOriginal.hidden = true;
      } else {
        cutStatus.textContent = "No Vidcut cut file found. Choose the original video and Vidcut will find the matching parts by comparing the sound (takes a minute or two for a long video).";
      }
    } catch { cutStatus.textContent = "Choose the original video to match against."; }
  };
  mode.addEventListener("change", () => { cutBox.hidden = mode.value !== "cut"; if (mode.value === "cut") lookForManifest(); });
  clipSel.addEventListener("change", () => mode.value === "cut" && lookForManifest());
  const dlg = el("dialog", { class: "frame-dialog import-dialog" },
    el("h3", {}, `Import subtitles from ${fileName}`),
    el("p", { class: "muted small" }, "For the times to match, the caption file must belong to the video it is applied to, or to the original that this clip was cut from."),
    el("label", { class: "field" }, el("span", {}, "Apply subtitles to clip"), clipSel),
    el("label", { class: "field" }, el("span", {}, "These captions were"), mode), cutBox,
    el("label", { class: "field inline" }, el("span", {}, p.selection ? "Only the selected In/Out range" : "Only the In/Out range (none selected)"), onlySel),
    el("label", { class: "field" }, el("span", {}, "Time shift (seconds): positive = subtitles appear later (use when they show before the voice) · negative = earlier (use when they show after the voice)"), offset),
    el("div", { class: "row" },
      el("button", { onclick: () => dlg.close() }, "Cancel"),
      el("button", { class: "primary", onclick: async () => {
        const clipId = clipSel.value;
        if (mode.value === "cut" && !pieces) return showToast("Choose the original video first, so the times can be matched", "error", 6000);
        if (getProject().subtitles.some((x) => x.clip_id === clipId) && !confirm("This clip's existing subtitles will be replaced. Continue?")) return;
        dlg.close();
        try {
          const r = await withSavedProject(() => api("POST", "/api/subtitles/import-srt", {
            clip_id: clipId, srt_text: srtText, offset: parseFloat(offset.value) || 0, only_selection: onlySel.checked,
            ...(mode.value === "cut" ? { pieces } : {}) }));
          await loadProject();
          showToast(`Imported ${r.count} subtitle lines`);
        } catch (e) {
          showError(e);
        }
      } }, "Import")));
  dlg.addEventListener("close", () => dlg.remove());
  document.body.append(dlg);
  dlg.showModal();
}

function addBlank() {
  const p = getProject();
  const hit = tm.editedToSource(p.clips, player.getTime());
  if (!hit) return showToast("Add a clip and keep at least one section first", "error");
  const [clipId, t] = hit;
  const keeps = tm.enabledKeeps(p.clips.find((c) => c.id === clipId));
  const keepEnd = keeps.find((k) => t >= k.start && t <= k.end)?.end ?? t + 2;
  const id = crypto.randomUUID().replaceAll("-", "");
  update((q) => q.subtitles.push({ id, clip_id: clipId, src_start: t, src_end: Math.min(t + 2, Math.max(keepEnd, t + 0.5)),
    text: "Type text", x: null, y: null }), "subs");
  setSelectedSub(id);
}

// Characters you actually see: Thai vowel/tone marks that sit on a letter are not counted, nor is whitespace.
export const charCount = (text) => [...text].filter((ch) => !/[\s\u0E31\u0E34-\u0E3A\u0E47-\u0E4E]/.test(ch)).length;

function splitAt(id, pos) {
  const p = getProject();
  const s = p.subtitles.find((x) => x.id === id);
  const head = s.text.slice(0, pos).trim(), tail = s.text.slice(pos).trim();
  if (!head || !tail) return showToast("Put the cursor inside the text where the line should break", "error");
  const frac = charCount(head) / Math.max(1, charCount(head) + charCount(tail));
  const mid = s.src_start + (s.src_end - s.src_start) * frac;
  const newId = crypto.randomUUID().replaceAll("-", "");
  update((q) => {
    const a = q.subtitles.find((x) => x.id === id);
    const b = { ...a, id: newId, src_start: mid, text: tail };
    a.src_end = mid;
    a.text = head;
    q.subtitles.push(b);
  }, "subs");
}

function mergeWithNext(id, nextId) {
  update((q) => {
    const a = q.subtitles.find((x) => x.id === id), b = q.subtitles.find((x) => x.id === nextId);
    a.text = `${a.text} ${b.text}`.trim();
    a.src_end = Math.max(a.src_end, b.src_end);
    q.subtitles = q.subtitles.filter((x) => x.id !== nextId);
  }, "subs");
}

function deleteAll() {
  const n = getProject().subtitles.length;
  if (!n) return showToast("There are no subtitles to delete", "error");
  if (!confirm(`Delete all ${n} subtitles? This can't be undone.`)) return;
  update((q) => (q.subtitles = []), "subs");
  setSelectedSub(null);
  showToast(`Deleted ${n} subtitles`);
}

export function initSubtitles() {
  const root = $("#subs-panel");
  const model = el("select", {}, Object.keys(MODELS).map((m) => el("option", { value: m }, m)));
  model.value = recall("vidcut.model", "large-v3");
  const note = el("p", { class: "muted small" }, MODELS[model.value]);
  model.addEventListener("change", () => (remember("vidcut.model", model.value), (note.textContent = MODELS[model.value])));
  const list = el("div", { class: "sub-list" });
  const rewrapChars = el("input", { type: "number", id: "rewrap-chars", class: "num", min: 4, max: 80, step: 1, value: recall("vidcut.rewrapChars", 14) });
  const rewrapLines = el("input", { type: "number", id: "rewrap-lines", class: "num", min: 1, max: 4, step: 1, value: recall("vidcut.rewrapLines", 2) });
  const rewrapAll = async () => {
    const chars = +rewrapChars.value, lines = +rewrapLines.value;
    remember("vidcut.rewrapChars", chars); remember("vidcut.rewrapLines", lines);
    if (!getProject().subtitles.length) return showToast("There are no subtitles to re-wrap", "error");
    try {
      const r = await withSavedProject(() => api("POST", "/api/subtitles/rewrap", { max_chars: chars, max_lines: lines }));
      await loadProject();
      showToast(`Re-wrapped to ${chars} characters per line (${r.before} → ${r.after} subtitles). Ctrl+Z undoes it.`, "info", 6000);
    } catch (e) { showError(e); }
  };
  const srtInput = el("input", { type: "file", id: "srt-file", accept: ".srt,.vtt,.sbv,.txt,text/plain", hidden: true });
  srtInput.addEventListener("change", async () => {
    const file = srtInput.files[0];
    srtInput.value = ""; // choosing the same file again must fire 'change' again
    if (file) openImportDialog(file.name, await file.text());
  });
  root.replaceChildren(
    el("h2", {}, "Subtitles"),
    el("label", { class: "field" }, el("span", {}, "Transcription model"), model), note,
    el("div", { class: "row" },
      el("button", { class: "primary", onclick: () => generate(model.value) }, "Generate subtitles"),
      el("button", { onclick: addBlank }, "+ Add subtitle")),
    el("div", { class: "field rewrap" }, el("span", {}, "Re-wrap every subtitle"),
      el("div", { class: "row" },
        el("label", { title: "TikTok 9:16 starts at 14, YouTube 16:9 at 36" }, "Characters per line ", rewrapChars), el("label", {}, "Lines ", rewrapLines),
        el("button", { id: "btn-rewrap", title: "Re-flow all subtitles to this many characters per line (breaks only between words)", onclick: rewrapAll }, "Apply to all"))),
    el("div", { class: "row" },
      el("button", { title: "Import subtitles from an .srt, .vtt or .sbv file, e.g. downloaded from YouTube Studio", onclick: () => srtInput.click() }, "Import .srt / .vtt / .sbv file"),
      srtInput,
      el("button", { class: "danger", id: "btn-delete-all-subs", title: "Delete every subtitle in the project", onclick: deleteAll }, "Delete all subtitles")),
    list);

  const toolRefs = new Map(); // "<id>:x" | "<id>:y" | "<id>:size" -> the row's inputs, to follow drags on the preview
  const syncTools = () => {
    const p = getProject();
    for (const r of toolRefs.values()) {
      const s = p.subtitles.find((x) => x.id === r.id);
      if (!s) continue;
      if (r.size) { if (!r.size.focused()) r.size.sync(s.scale ?? 1); } else if (document.activeElement !== r.input) r.input.value = s[r.axis] != null ? String(Math.round(s[r.axis] * 100)) : "";
    }
  };
  const render = () => {
    const p = getProject();
    if (!p) return; // not loaded yet
    toolRefs.clear();
    const index = tm.spanIndex(p.clips);
    const rows = p.subtitles.map((s) => ({ s, span: tm.subtitleEditedSpan(p.clips, s, index) }))
      .sort((a, b) => (a.span ? a.span[0] : 1e9 + a.s.src_start) - (b.span ? b.span[0] : 1e9 + b.s.src_start));
    list.replaceChildren(...(rows.length ? rows.map(({ s, span }, i) => {
      const ta = el("textarea", { rows: 2, "aria-label": "Subtitle text" });
      ta.value = s.text;
      const count = el("span", { class: "muted small chars" }, `${charCount(s.text)} chars`);
      const next = rows[i + 1]?.s.clip_id === s.clip_id ? rows[i + 1].s : null;
      const size = numberSlider({ min: 0.4, max: 3, step: 0.05, value: s.scale ?? 1, unit: "%", label: "Size of this line (percent)",
        toDisplay: (v) => v * 100, fromDisplay: (d) => d / 100,
        onInput: (v) => update((q) => (q.subtitles.find((x) => x.id === s.id).scale = Math.abs(v - 1) < 0.001 ? null : v), "subs-pos") });
      size.root.title = "Size of this line only (double-click to reset)";
      size.root.addEventListener("dblclick", () => (size.sync(1), update((q) => (q.subtitles.find((x) => x.id === s.id).scale = null), "subs-pos")));
      // position as typed percentages of the frame; empty = the style's default position
      const pos = (axis) => {
        const input = el("input", { type: "number", class: "num", min: 0, max: 100, step: 1, placeholder: "auto", "aria-label": `${axis === "x" ? "Horizontal" : "Vertical"} position of this line (percent)` });
        if (s[axis] != null) input.value = String(Math.round(s[axis] * 100));
        input.addEventListener("change", () => {
          const d = parseFloat(input.value);
          update((q) => { const t = q.subtitles.find((x) => x.id === s.id); t[axis] = Number.isFinite(d) ? Math.min(1, Math.max(0, d / 100)) : null; }, "subs-pos");
        });
        toolRefs.set(`${s.id}:${axis}`, { input, axis, id: s.id });
        return input;
      };
      toolRefs.set(`${s.id}:size`, { size, id: s.id });
      ta.addEventListener("input", () => {
        count.textContent = `${charCount(ta.value)} chars`;
        update((q) => (q.subtitles.find((x) => x.id === s.id).text = ta.value), "subs-text");
      });
      ta.addEventListener("focus", () => ui.selectedSubId !== s.id && setSelectedSub(s.id));
      return el("div", { class: `sub-row${s.id === ui.selectedSubId ? " selected" : ""}${span ? "" : " hidden-sub"}`, "data-id": s.id },
        el("button", { class: "ghost time", title: "Go to this subtitle", onclick: () => { setSelectedSub(s.id); span && player.seek(span[0]); } },
          span ? fmtTime(span[0]) : "hidden"),
        ta,
        el("button", { class: "ghost icon", title: "Delete this subtitle", onclick: () => update((q) => (q.subtitles = q.subtitles.filter((x) => x.id !== s.id)), "subs") }, "✕"),
        span ? "" : el("span", { class: "muted small" }, "Inside a cut section, so it won't be exported"),
        el("div", { class: "sub-tools" }, count, size.root),
        el("div", { class: "sub-tools" }, el("span", { class: "muted small" }, "X"), pos("x"), el("span", { class: "muted small" }, "Y"), pos("y"),
          el("button", { class: "ghost small", title: "Back to the style's position and size", onclick: () => update((q) => { const t = q.subtitles.find((x) => x.id === s.id); t.x = t.y = t.scale = null; }, "subs") }, "Reset"),
          el("button", { class: "ghost small", title: "Break this line at the text cursor", onclick: () => splitAt(s.id, ta.selectionStart) }, "Split"),
          next ? el("button", { class: "ghost small", title: "Join with the next line", onclick: () => mergeWithNext(s.id, next.id) }, "Merge ↓") : ""));
    }) : [el("p", { class: "muted small" }, "No subtitles yet. Set In/Out, then click “Generate subtitles”")]));
  };
  subscribe((why) => {
    if (why === "select") {
      // only restyle: rebuilding the list here would destroy the textarea that was just focused
      list.querySelectorAll(".sub-row").forEach((r) => r.classList.toggle("selected", r.dataset.id === ui.selectedSubId));
    } else if (why === "subs-pos") {
      syncTools();
    } else if (!["subs-text", "selection", "confirm", "preset", "safezone", "style"].includes(why) && !why.startsWith("ov-")) render();
  });
  render();
  setSubtitleLane(paintLane, laneHandler);
}

// ---- subtitle lane on the edit timeline ----------------------------------------------------
let rects = []; // [{ sub, x0, x1 }] from the last paint, in canvas CSS px
let laneDrag = null;
const EDGE = 6;

function paintLane(ctx, w, h, xAt) {
  const p = getProject();
  const top = LANE_TOP + 5, bh = h - LANE_TOP - 10;
  ctx.fillStyle = cssVar("--lane");
  ctx.fillRect(0, LANE_TOP, w, h - LANE_TOP);
  ctx.font = "12px 'Leelawadee UI', Sarabun, system-ui, sans-serif";
  rects = [];
  const index = tm.spanIndex(p.clips);
  for (const sub of p.subtitles) {
    const span = tm.subtitleEditedSpan(p.clips, sub, index);
    if (!span) continue;
    const x0 = xAt(span[0], w), x1 = xAt(span[1], w);
    if (x1 < 0 || x0 > w) continue;
    rects.push({ sub, x0, x1 });
    const sel = sub.id === ui.selectedSubId;
    ctx.fillStyle = sel ? cssVar("--sub-sel") : cssVar("--sub");
    ctx.fillRect(x0, top, Math.max(2, x1 - x0), bh);
    ctx.fillStyle = cssVar("--accent");
    ctx.fillRect(x0, top, 2, bh);
    ctx.fillRect(x1 - 2, top, 2, bh);
    ctx.save();
    ctx.beginPath();
    ctx.rect(x0 + 3, top, Math.max(0, x1 - x0 - 6), bh);
    ctx.clip();
    ctx.fillStyle = cssVar("--text");
    ctx.fillText(sub.text.split("\n")[0], x0 + 6, top + bh / 2 + 4);
    ctx.restore();
  }
}

/**
 * Which subtitle part is under the pointer. Edges beat bodies; the nearest edge wins. Abutting
 * subtitles share an x, so ties go to the selected subtitle, then to the earlier one's end.
 */
function hit(e) {
  const x = e.offsetX;
  const edges = [];
  for (const r of rects) {
    if (Math.abs(x - r.x0) <= EDGE) edges.push({ sub: r.sub, part: "start", d: Math.abs(x - r.x0) });
    if (Math.abs(x - r.x1) <= EDGE) edges.push({ sub: r.sub, part: "end", d: Math.abs(x - r.x1) });
  }
  if (edges.length) {
    const selected = (c) => (c.sub.id === ui.selectedSubId ? 0 : 1);
    edges.sort((a, b) => (Math.abs(a.d - b.d) > 0.5 ? a.d - b.d : selected(a) - selected(b) || (a.part === "end" ? -1 : 1) - (b.part === "end" ? -1 : 1)));
    return edges[0];
  }
  const body = rects.find((r) => x >= r.x0 && x <= r.x1);
  return body ? { sub: body.sub, part: "body" } : null;
}

const laneHandler = {
  hover(e) {
    const h = hit(e);
    return h ? (h.part === "body" ? "pointer" : "ew-resize") : null;
  },
  down(e) {
    const h = hit(e);
    if (!h) return false;
    setSelectedSub(h.sub.id);
    if (h.part === "body") {
      const span = spanOf(h.sub);
      span && player.seek(span[0]);
    } else laneDrag = h;
    return true;
  },
  move(e) {
    if (!laneDrag) return;
    const { sub, part } = laneDrag;
    const src = tm.dragEdgeToSource(getProject().clips, sub, part, timeAtX(e.offsetX));
    update((q) => (q.subtitles.find((s) => s.id === sub.id)[part === "start" ? "src_start" : "src_end"] = src), "subs");
    laneDrag.sub = getProject().subtitles.find((s) => s.id === sub.id);
  },
  up() { laneDrag = null; },
};
