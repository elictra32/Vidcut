// Subtitle panel (auto-generate, list, edit text), and the subtitle lane on the edit timeline.
import { api } from "./api.js";
import { getProject, loadProject, reloadAfterJob, setSelectedSub, subscribe, ui, update, withSavedProject } from "./state.js";
import { trackJob } from "./status.js";
import { showError, showToast } from "./toast.js";
import * as tm from "./timeline_math.js";
import * as player from "./player.js";
import { LANE_TOP, setSubtitleLane, timeAtX } from "./timeline_view.js";
import { $, basename, cssVar, el, fmtTime } from "./util.js";

const MODELS = {
  "large-v3": "Most accurate · first use downloads about 3 GB · slowest on CPU",
  medium: "Balanced · first use downloads about 1.5 GB",
  small: "Fastest · about 500 MB download · less accurate",
};
const spanOf = (s) => tm.subtitleEditedSpan(getProject().clips, s);

function remember(key, value) {
  try { localStorage.setItem(key, value); } catch { /* storage blocked: the choice just isn't remembered */ }
}
function recall(key, fallback) {
  try { return localStorage.getItem(key) ?? fallback; } catch { return fallback; }
}

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
  const dlg = el("dialog", { class: "frame-dialog import-dialog" },
    el("h3", {}, `Import subtitles from ${fileName}`),
    el("p", { class: "muted small" }, "The SRT must come from the same video you added here (the original, before dead air was cut) for the times to match"),
    el("label", { class: "field" }, el("span", {}, "Apply subtitles to clip"), clipSel),
    el("label", { class: "field inline" }, el("span", {}, p.selection ? "Only the selected In/Out range" : "Only the In/Out range (none selected)"), onlySel),
    el("label", { class: "field" }, el("span", {}, "Time shift (seconds): positive = subtitles appear later (use when they show before the voice) · negative = earlier (use when they show after the voice)"), offset),
    el("div", { class: "row" },
      el("button", { onclick: () => dlg.close() }, "Cancel"),
      el("button", { class: "primary", onclick: async () => {
        const clipId = clipSel.value;
        if (getProject().subtitles.some((x) => x.clip_id === clipId) && !confirm("This clip's existing subtitles will be replaced. Continue?")) return;
        dlg.close();
        try {
          const r = await withSavedProject(() => api("POST", "/api/subtitles/import-srt", {
            clip_id: clipId, srt_text: srtText, offset: parseFloat(offset.value) || 0, only_selection: onlySel.checked }));
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

export function initSubtitles() {
  const root = $("#subs-panel");
  const model = el("select", {}, Object.keys(MODELS).map((m) => el("option", { value: m }, m)));
  model.value = recall("vidcut.model", "large-v3");
  const note = el("p", { class: "muted small" }, MODELS[model.value]);
  model.addEventListener("change", () => (remember("vidcut.model", model.value), (note.textContent = MODELS[model.value])));
  const list = el("div", { class: "sub-list" });
  const srtInput = el("input", { type: "file", id: "srt-file", accept: ".srt,.txt,text/plain", hidden: true });
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
    el("div", { class: "row" },
      el("button", { title: "Import subtitles from an .srt file, e.g. downloaded from YouTube Studio", onclick: () => srtInput.click() }, "Import .srt file"),
      srtInput),
    list);

  const render = () => {
    const p = getProject();
    if (!p) return; // not loaded yet
    const rows = p.subtitles.map((s) => ({ s, span: spanOf(s) }))
      .sort((a, b) => (a.span ? a.span[0] : 1e9 + a.s.src_start) - (b.span ? b.span[0] : 1e9 + b.s.src_start));
    list.replaceChildren(...(rows.length ? rows.map(({ s, span }) => {
      const ta = el("textarea", { rows: 2, "aria-label": "Subtitle text" });
      ta.value = s.text;
      ta.addEventListener("input", () => update((q) => (q.subtitles.find((x) => x.id === s.id).text = ta.value), "subs-text"));
      ta.addEventListener("focus", () => ui.selectedSubId !== s.id && setSelectedSub(s.id));
      return el("div", { class: `sub-row${s.id === ui.selectedSubId ? " selected" : ""}${span ? "" : " hidden-sub"}`, "data-id": s.id },
        el("button", { class: "ghost time", title: "Go to this subtitle", onclick: () => { setSelectedSub(s.id); span && player.seek(span[0]); } },
          span ? fmtTime(span[0]) : "hidden"),
        ta,
        el("button", { class: "ghost icon", title: "Delete this subtitle", onclick: () => update((q) => (q.subtitles = q.subtitles.filter((x) => x.id !== s.id)), "subs") }, "✕"),
        span ? "" : el("span", { class: "muted small" }, "Inside a cut section, so it won't be exported"));
    }) : [el("p", { class: "muted small" }, "No subtitles yet. Set In/Out, then click “Generate subtitles”")]));
  };
  subscribe((why) => {
    if (why === "select") {
      // only restyle: rebuilding the list here would destroy the textarea that was just focused
      list.querySelectorAll(".sub-row").forEach((r) => r.classList.toggle("selected", r.dataset.id === ui.selectedSubId));
    } else if (why !== "subs-text" && why !== "subs-pos") render();
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
  for (const sub of p.subtitles) {
    const span = spanOf(sub);
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
