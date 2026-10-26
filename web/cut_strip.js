// The cut strip: SOURCE time of the current clip, with every keep and every removed gap
// visible. Click a kept segment to cut it, or a removed region to bring it back.
import { getProject, subscribe, ui, updateKeeps } from "./state.js";
import * as player from "./player.js";
import * as tm from "./timeline_math.js";
import { ensurePeaks, peakMax } from "./waveforms.js";
import { $, cssVar, el, fitCanvas, fmtTime, rafThrottle } from "./util.js";

let canvas, hint;
let view = { start: 0, end: 60 };
let viewClipId = null;
let press = null;

const clip = () => getProject()?.clips.find((c) => c.id === ui.currentClipId) ?? null;
const timeAt = (x) => view.start + (x / canvas.getBoundingClientRect().width) * (view.end - view.start);
const xAt = (t, w) => ((t - view.start) / (view.end - view.start)) * w;

function fit() {
  const c = clip();
  view = { start: 0, end: Math.max(c?.duration ?? 1, 1) };
  viewClipId = c?.id ?? null;
}

function clamp() {
  const c = clip();
  if (!c) return;
  const span = Math.min(Math.max(view.end - view.start, 1), c.duration);
  const start = Math.min(Math.max(view.start, 0), c.duration - span);
  view = { start, end: start + span };
}

/** Sorted enabled-or-not keeps plus the gaps between them, as [start, end, kind, keepRef]. */
function regions(c) {
  const keeps = [...c.keeps].sort((a, b) => a.start - b.start);
  const out = [];
  let t = 0;
  for (const k of keeps) {
    if (k.start - t > 0.01) out.push([t, k.start, "gap", null]);
    out.push([k.start, k.end, k.enabled ? "keep" : "off", k]);
    t = Math.max(t, k.end);
  }
  if (c.duration - t > 0.01) out.push([t, c.duration, "gap", null]);
  return out;
}

const draw = rafThrottle(() => {
  const c = clip();
  if (!canvas) return;
  const { ctx, w, h } = fitCanvas(canvas);
  ctx.fillStyle = cssVar("--panel-2");
  ctx.fillRect(0, 0, w, h);
  if (!c) {
    ctx.fillStyle = cssVar("--muted");
    ctx.font = "14px system-ui, sans-serif";
    ctx.fillText("ยังไม่มีคลิป", 16, h / 2);
    return;
  }
  if (viewClipId !== c.id) fit();
  const mid = h / 2 + 6;
  for (const [a, b, kind] of regions(c)) {
    const x0 = xAt(a, w), x1 = xAt(b, w);
    if (x1 < 0 || x0 > w) continue;
    ctx.fillStyle = kind === "keep" ? cssVar("--keep-fill") : cssVar("--cut-fill");
    ctx.fillRect(x0, 14, x1 - x0, h - 14);
    ctx.fillStyle = kind === "keep" ? cssVar("--keep") : cssVar("--cut");
    ctx.fillRect(x0, 10, Math.max(1, x1 - x0), 4);
  }
  const spp = (view.end - view.start) / w;
  ctx.fillStyle = cssVar("--wave");
  for (let x = 0; x < w; x++) {
    const t0 = view.start + x * spp;
    const half = Math.max(1, peakMax(c.id, t0, t0 + spp) * (h / 2 - 20));
    ctx.fillRect(x, mid - half, 1, half * 2);
  }
  // selection mapped back onto this clip's source time
  const sel = getProject().selection;
  if (sel) {
    ctx.fillStyle = cssVar("--select");
    let pieces = [];
    try { pieces = tm.selectionPieces(getProject().clips, sel); } catch { /* stale selection: draw none */ }
    for (const pc of pieces.filter((q) => q.clipId === c.id)) {
      ctx.fillRect(xAt(pc.srcStart, w), 0, Math.max(2, xAt(pc.srcEnd, w) - xAt(pc.srcStart, w)), 5);
    }
  }
  if (player.getLoadedClipId() === c.id) {
    ctx.fillStyle = cssVar("--playhead");
    ctx.fillRect(Math.round(xAt(player.getSourceTime(), w)) - 1, 0, 2, h);
  }
  ctx.fillStyle = cssVar("--muted");
  ctx.font = "11px system-ui, sans-serif";
  ctx.fillText(`${fmtTime(view.start)} – ${fmtTime(view.end)}`, 6, h - 5);
});

function toggleAt(t) {
  const c = clip();
  if (!c) return;
  const hit = regions(c).find(([a, b]) => t >= a && t <= b);
  if (!hit) return;
  const [a, b, kind, keep] = hit;
  updateKeeps((p) => {
    const target = p.clips.find((x) => x.id === c.id);
    if (kind === "gap") target.keeps.push({ start: a, end: b, enabled: true });
    else {
      const k = target.keeps.find((x) => x.start === keep.start && x.end === keep.end);
      k.enabled = !k.enabled;
    }
    target.keeps.sort((x, y) => x.start - y.start);
  });
}

export function initCutStrip() {
  const wrap = $("#cut-strip-wrap");
  canvas = el("canvas", { class: "timeline-canvas", height: 110 });
  hint = el("span", { class: "muted" }, "คลิกช่วงสีเขียวเพื่อตัดออก · คลิกช่วงสีแดงเพื่อเอากลับมา · เลื่อนล้อเมาส์เพื่อซูม ลากเพื่อเลื่อน");
  wrap.replaceChildren(
    el("div", { class: "tl-bar" }, el("strong", {}, "ตรวจช่วงที่ตัด (เวลาในไฟล์ต้นฉบับ)"), el("span", { class: "spacer" }), hint,
      el("button", { class: "ghost", onclick: () => (fit(), draw()) }, "ทั้งคลิป")),
    canvas);

  canvas.addEventListener("pointerdown", (e) => {
    canvas.setPointerCapture(e.pointerId);
    press = { x: e.offsetX, start: view.start, end: view.end, moved: false };
  });
  canvas.addEventListener("pointermove", (e) => {
    if (!press) return;
    if (Math.abs(e.offsetX - press.x) > 4) press.moved = true;
    if (!press.moved) return;
    const dt = ((press.x - e.offsetX) / canvas.getBoundingClientRect().width) * (press.end - press.start);
    view = { start: press.start + dt, end: press.end + dt };
    clamp();
    draw();
  });
  canvas.addEventListener("pointerup", (e) => {
    if (press && !press.moved) toggleAt(timeAt(e.offsetX));
    press = null;
  });
  canvas.addEventListener("wheel", (e) => {
    e.preventDefault();
    const a = timeAt(e.offsetX), f = Math.exp(e.deltaY * 0.002);
    view = { start: a - (a - view.start) * f, end: a + (view.end - a) * f };
    clamp();
    draw();
  }, { passive: false });

  subscribe((why) => {
    if (why === "load") getProject().clips.forEach((c) => ensurePeaks(c, draw));
    draw();
  });
  player.onTime(draw);
  new ResizeObserver(draw).observe(canvas);
}
