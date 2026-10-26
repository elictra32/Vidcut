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
  "large-v3": "แม่นที่สุด · ครั้งแรกต้องดาวน์โหลดราว 3 GB · ช้าสุดบน CPU",
  medium: "สมดุล · ครั้งแรกดาวน์โหลดราว 1.5 GB",
  small: "เร็วที่สุด · ดาวน์โหลดราว 500 MB · แม่นน้อยกว่า",
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
  if (!p.selection) return showToast("ตั้งช่วงที่จะใช้ก่อน (ปุ่ม ตั้ง In / ตั้ง Out) จะได้ถอดเสียงเฉพาะช่วงนั้น", "error", 6000);
  if (p.subtitles.length && !confirm("ซับที่มีอยู่จะถูกแทนที่ด้วยซับที่สร้างใหม่ ทำต่อไหม?")) return;
  try {
    const { job } = await withSavedProject(() => api("POST", "/api/transcribe", { model })); // the server uses its saved copy
    const done = await trackJob("กำลังถอดเสียง (อาจใช้เวลาหลายนาทีบน CPU)", job);
    if (!done) return;
    await reloadAfterJob();
    if (done.result.empty) showToast("ไม่พบเสียงพูดในช่วงที่เลือก ลองเลือกช่วงอื่น หรือกด “+ เพิ่มซับ” เพื่อพิมพ์เอง", "error", 7000);
    else showToast(`สร้างซับแล้ว ${done.result.count} บรรทัด`);
  } catch (e) {
    showError(e);
  }
}

/** Import an .srt (e.g. YouTube auto captions). Times are source times of the SAME uncut video. */
function openImportDialog(fileName, srtText) {
  const p = getProject();
  if (!p.clips.length) return showToast("เพิ่มคลิปก่อน แล้วค่อยนำเข้าซับ", "error");
  const clipSel = el("select", {}, p.clips.map((c) => el("option", { value: c.id }, basename(c.path))));
  clipSel.value = p.clips.some((c) => c.id === ui.currentClipId) ? ui.currentClipId : p.clips[0].id;
  const onlySel = el("input", { type: "checkbox", checked: !!p.selection, disabled: !p.selection });
  const offset = el("input", { type: "number", value: 0, step: 0.1 });
  const dlg = el("dialog", { class: "frame-dialog import-dialog" },
    el("h3", {}, `นำเข้าซับจาก ${fileName}`),
    el("p", { class: "muted small" }, "ไฟล์ SRT ต้องมาจากวิดีโอไฟล์เดียวกับที่ใส่ในโปรแกรม (ไฟล์ต้นฉบับก่อนตัด Dead air) เวลาจึงจะตรงกัน"),
    el("label", { class: "field" }, el("span", {}, "ใส่ซับให้กับคลิป"), clipSel),
    el("label", { class: "field inline" }, el("span", {}, p.selection ? "เฉพาะช่วง In/Out ที่เลือก" : "เฉพาะช่วง In/Out (ยังไม่ได้เลือกช่วง)"), onlySel),
    el("label", { class: "field" }, el("span", {}, "เลื่อนเวลา (วินาที) ใส่ค่าบวกถ้าซับมาช้าไป"), offset),
    el("div", { class: "row" },
      el("button", { onclick: () => dlg.close() }, "ยกเลิก"),
      el("button", { class: "primary", onclick: async () => {
        const clipId = clipSel.value;
        if (getProject().subtitles.some((x) => x.clip_id === clipId) && !confirm("ซับเดิมของคลิปนี้จะถูกแทนที่ ทำต่อไหม?")) return;
        dlg.close();
        try {
          const r = await withSavedProject(() => api("POST", "/api/subtitles/import-srt", {
            clip_id: clipId, srt_text: srtText, offset: parseFloat(offset.value) || 0, only_selection: onlySel.checked }));
          await loadProject();
          showToast(`นำเข้าซับแล้ว ${r.count} บรรทัด`);
        } catch (e) {
          showError(e);
        }
      } }, "นำเข้า")));
  dlg.addEventListener("close", () => dlg.remove());
  document.body.append(dlg);
  dlg.showModal();
}

function addBlank() {
  const p = getProject();
  const hit = tm.editedToSource(p.clips, player.getTime());
  if (!hit) return showToast("เพิ่มคลิปและเปิดช่วงที่เก็บไว้ก่อน", "error");
  const [clipId, t] = hit;
  const keeps = tm.enabledKeeps(p.clips.find((c) => c.id === clipId));
  const keepEnd = keeps.find((k) => t >= k.start && t <= k.end)?.end ?? t + 2;
  const id = crypto.randomUUID().replaceAll("-", "");
  update((q) => q.subtitles.push({ id, clip_id: clipId, src_start: t, src_end: Math.min(t + 2, Math.max(keepEnd, t + 0.5)),
    text: "พิมพ์ข้อความ", x: null, y: null }), "subs");
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
    el("h2", {}, "ซับไตเติล"),
    el("label", { class: "field" }, el("span", {}, "โมเดลถอดเสียง"), model), note,
    el("div", { class: "row" },
      el("button", { class: "primary", onclick: () => generate(model.value) }, "สร้างซับอัตโนมัติ"),
      el("button", { onclick: addBlank }, "+ เพิ่มซับ")),
    el("div", { class: "row" },
      el("button", { title: "นำเข้าซับจากไฟล์ .srt เช่นที่ดาวน์โหลดจาก YouTube Studio", onclick: () => srtInput.click() }, "นำเข้าไฟล์ .srt"),
      srtInput),
    list);

  const render = () => {
    const p = getProject();
    if (!p) return; // not loaded yet
    const rows = p.subtitles.map((s) => ({ s, span: spanOf(s) }))
      .sort((a, b) => (a.span ? a.span[0] : 1e9 + a.s.src_start) - (b.span ? b.span[0] : 1e9 + b.s.src_start));
    list.replaceChildren(...(rows.length ? rows.map(({ s, span }) => {
      const ta = el("textarea", { rows: 2, "aria-label": "ข้อความซับ" });
      ta.value = s.text;
      ta.addEventListener("input", () => update((q) => (q.subtitles.find((x) => x.id === s.id).text = ta.value), "subs-text"));
      ta.addEventListener("focus", () => ui.selectedSubId !== s.id && setSelectedSub(s.id));
      return el("div", { class: `sub-row${s.id === ui.selectedSubId ? " selected" : ""}${span ? "" : " hidden-sub"}`, "data-id": s.id },
        el("button", { class: "ghost time", title: "ไปที่ซับนี้", onclick: () => { setSelectedSub(s.id); span && player.seek(span[0]); } },
          span ? fmtTime(span[0]) : "ซ่อน"),
        ta,
        el("button", { class: "ghost icon", title: "ลบซับนี้", onclick: () => update((q) => (q.subtitles = q.subtitles.filter((x) => x.id !== s.id)), "subs") }, "✕"),
        span ? "" : el("span", { class: "muted small" }, "อยู่ในช่วงที่ตัดออก จึงไม่ถูกส่งออก"));
    }) : [el("p", { class: "muted small" }, "ยังไม่มีซับ ตั้งช่วง In/Out แล้วกด “สร้างซับอัตโนมัติ”")]));
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
