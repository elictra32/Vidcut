// The edit timeline: EDITED time on the x axis (dead air already removed), with the
// waveform of what remains, the In/Out selection, and the playhead.
import { getProject, subscribe, update } from "./state.js";
import * as tm from "./timeline_math.js";
import * as player from "./player.js";
import { ensurePeaks, peakMax } from "./waveforms.js";
import { $, cssVar, el, fitCanvas, rafThrottle } from "./util.js";

const RULER_H = 22;
const WAVE_H = 84;
export const LANE_TOP = RULER_H + WAVE_H; // subtitle lane starts here (Task 10)
const HANDLE_PX = 7;
const MIN_SPAN = 2;

let canvas;
let view = { start: 0, end: 60 };
let drag = null;

const total = () => tm.editedDuration(getProject().clips);
const timeAt = (x) => view.start + (x / canvas.getBoundingClientRect().width) * (view.end - view.start);
const xAt = (t, w) => ((t - view.start) / (view.end - view.start)) * w;

export function fitView() {
  const p = getProject();
  const tot = total();
  const s = p.selection;
  if (s) {
    const pad = Math.max(1, (s.end - s.start) * 0.05);
    view = { start: Math.max(0, s.start - pad), end: Math.min(Math.max(tot, s.end), s.end + pad) };
  } else view = { start: 0, end: Math.max(tot, MIN_SPAN) };
  draw();
}

function clampView() {
  const tot = Math.max(total(), MIN_SPAN);
  let span = Math.min(Math.max(view.end - view.start, MIN_SPAN), tot);
  let start = Math.min(Math.max(view.start, 0), tot - span);
  view = { start, end: start + span };
}

function zoom(factor, anchorT) {
  const a = anchorT ?? (view.start + view.end) / 2;
  view = { start: a - (a - view.start) * factor, end: a + (view.end - a) * factor };
  clampView();
  draw();
}

function tickStep(span) {
  for (const s of [0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 1800]) if (span / s <= 14) return s;
  return 3600;
}

const draw = rafThrottle(() => {
  const p = getProject();
  if (!canvas || !p) return;
  const { ctx, w, h } = fitCanvas(canvas);
  ctx.fillStyle = cssVar("--panel-2");
  ctx.fillRect(0, 0, w, h);
  const tot = total();
  if (!tot) {
    ctx.fillStyle = cssVar("--muted");
    ctx.font = "14px system-ui, sans-serif";
    ctx.fillText("Add a clip to start editing", 16, h / 2);
    return;
  }
  ctx.font = "11px system-ui, sans-serif";
  const step = tickStep(view.end - view.start);
  ctx.fillStyle = cssVar("--muted");
  ctx.strokeStyle = cssVar("--grid");
  for (let t = Math.ceil(view.start / step) * step; t <= view.end; t += step) {
    const x = Math.round(xAt(t, w)) + 0.5;
    ctx.beginPath(); ctx.moveTo(x, RULER_H - 5); ctx.lineTo(x, h); ctx.stroke();
    ctx.fillText(`${Math.floor(t / 60)}:${String(Math.floor(t % 60)).padStart(2, "0")}`, x + 3, 12);
  }
  // waveform of the remaining (kept) audio
  const segs = tm.segments(p.clips);
  const spp = (view.end - view.start) / w;
  const mid = RULER_H + WAVE_H / 2;
  ctx.fillStyle = cssVar("--wave");
  let si = 0;
  for (let x = 0; x < w; x++) {
    const t0 = view.start + x * spp, t1 = t0 + spp;
    while (si < segs.length && segs[si].editedStart + segs[si].len < t0) si++;
    let peak = 0;
    for (let j = si; j < segs.length && segs[j].editedStart < t1; j++) {
      const g = segs[j];
      const a = g.keep.start + Math.max(t0, g.editedStart) - g.editedStart;
      const b = g.keep.start + Math.min(t1, g.editedStart + g.len) - g.editedStart;
      peak = Math.max(peak, peakMax(g.clipId, a, Math.max(b, a)));
    }
    const half = Math.max(1, peak * (WAVE_H / 2 - 3));
    ctx.fillRect(x, mid - half, 1, half * 2);
  }
  // cut points between kept segments
  ctx.fillStyle = cssVar("--cut");
  for (const g of segs.slice(1)) {
    const x = xAt(g.editedStart, w);
    if (x >= 0 && x <= w) ctx.fillRect(Math.round(x), RULER_H, 1, WAVE_H);
  }
  // selection
  const s = p.selection;
  if (s) {
    const x0 = xAt(s.start, w), x1 = xAt(s.end, w);
    ctx.fillStyle = cssVar("--select-fill");
    ctx.fillRect(x0, RULER_H, x1 - x0, h - RULER_H);
    ctx.fillStyle = cssVar("--select");
    ctx.fillRect(x0 - 1, RULER_H, 3, h - RULER_H);
    ctx.fillRect(x1 - 2, RULER_H, 3, h - RULER_H);
    ctx.fillText("In", x0 + 4, RULER_H + 12);
    ctx.fillText("Out", x1 - 24, RULER_H + 12);
  }
  drawSubtitleLane?.(ctx, w, h, xAt);
  // playhead
  const px = xAt(player.getTime(), w);
  if (px >= 0 && px <= w) {
    ctx.fillStyle = cssVar("--playhead");
    ctx.fillRect(Math.round(px) - 1, 0, 2, h);
  }
});

/** The subtitle lane plugs in a painter and pointer handlers (see subtitles.js). */
let drawSubtitleLane = null;
let laneHandler = null;
export function setSubtitleLane(fn, handler) { drawSubtitleLane = fn; laneHandler = handler; draw(); }
export const xForTime = (t) => xAt(t, canvas.getBoundingClientRect().width);
export const redraw = draw;
export const getView = () => view;
export const timeAtX = (x) => timeAt(x);

function handleAt(x) {
  const s = getProject().selection;
  if (!s) return null;
  const w = canvas.getBoundingClientRect().width;
  if (Math.abs(x - xAt(s.start, w)) <= HANDLE_PX) return "start";
  if (Math.abs(x - xAt(s.end, w)) <= HANDLE_PX) return "end";
  return null;
}

function setEdge(which, t) {
  const tot = total();
  update((p) => {
    const s = p.selection;
    if (which === "start") p.selection = { start: Math.min(Math.max(0, t), s.end - 0.1), end: s.end };
    else p.selection = { start: s.start, end: Math.max(Math.min(tot, t), s.start + 0.1) };
  }, "selection");
}

export function initTimelineView() {
  const wrap = $("#edit-timeline-wrap");
  canvas = el("canvas", { class: "timeline-canvas", height: 150 });
  const bar = el("div", { class: "tl-bar" },
    el("strong", {}, "Timeline (after dead air cut)"),
    el("span", { class: "spacer" }),
    el("button", { class: "ghost", onclick: () => zoom(0.5, player.getTime()) }, "Zoom in"),
    el("button", { class: "ghost", onclick: () => zoom(2, player.getTime()) }, "Zoom out"),
    el("button", { class: "ghost", onclick: fitView }, "Fit"));
  wrap.replaceChildren(bar, canvas);

  canvas.addEventListener("pointerdown", (e) => {
    if (!total()) return;
    canvas.setPointerCapture(e.pointerId);
    const x = e.offsetX;
    if (e.offsetY >= LANE_TOP && laneHandler?.down(e)) {
      drag = { kind: "lane" };
      return;
    }
    const handle = handleAt(x);
    drag = { kind: handle ?? "scrub" };
    if (drag.kind === "scrub") player.seek(Math.min(Math.max(0, timeAt(x)), total()));
  });
  canvas.addEventListener("pointermove", (e) => {
    if (!drag) {
      canvas.style.cursor = (e.offsetY >= LANE_TOP && laneHandler?.hover(e)) || (total() && handleAt(e.offsetX) ? "ew-resize" : "default");
      return;
    }
    if (drag.kind === "lane") return laneHandler.move(e);
    const t = timeAt(e.offsetX);
    if (drag.kind === "scrub") player.seek(Math.min(Math.max(0, t), total()));
    else setEdge(drag.kind, t);
  });
  const end = () => {
    if (drag?.kind === "lane") laneHandler.up();
    drag = null;
  };
  canvas.addEventListener("pointerup", end);
  canvas.addEventListener("pointercancel", end);
  canvas.addEventListener("wheel", (e) => {
    e.preventDefault();
    if (e.shiftKey || Math.abs(e.deltaX) > Math.abs(e.deltaY)) {
      const d = ((e.deltaX || e.deltaY) / 500) * (view.end - view.start);
      view = { start: view.start + d, end: view.end + d };
      clampView();
      draw();
    } else zoom(Math.exp(e.deltaY * 0.002), timeAt(e.offsetX));
  }, { passive: false });

  const ensureAll = () => getProject()?.clips.forEach((c) => ensurePeaks(c, draw));
  subscribe((why) => {
    if (why === "load") { ensureAll(); fitView(); }
    if (why === "keeps") clampView();
    draw();
  });
  player.onTime((t) => {
    if (player.isPlaying() && (t < view.start || t > view.end)) {
      const span = view.end - view.start;
      view = { start: t - span * 0.1, end: t + span * 0.9 };
      clampView();
    }
    draw();
  });
  new ResizeObserver(draw).observe(canvas);
}
