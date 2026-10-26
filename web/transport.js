import { getProject, subscribe, update } from "./state.js";
import * as tm from "./timeline_math.js";
import { $, el, fmtTime } from "./util.js";
import * as player from "./player.js";

const DEFAULT_LEN = 90; // seconds: a typical 1-2 minute short

export function setIn(t) {
  const total = tm.editedDuration(getProject().clips);
  update((p) => {
    const s = p.selection;
    p.selection = s && t < s.end - 0.1 ? { start: t, end: s.end } : { start: t, end: Math.min(total, t + DEFAULT_LEN) };
  }, "selection");
}

export function setOut(t) {
  update((p) => {
    const s = p.selection;
    p.selection = s && t > s.start + 0.1 ? { start: s.start, end: t } : { start: Math.max(0, t - DEFAULT_LEN), end: t };
  }, "selection");
}

export const clearSelection = () => update((p) => (p.selection = null), "selection");

export function initTransport() {
  const root = $("#transport");
  const playBtn = el("button", { class: "primary", title: "Play/Pause (Space)", onclick: () => player.toggle() }, "▶ Play");
  const clock = el("span", { class: "clock" }, "0:00.0 / 0:00.0");
  const selInfo = el("span", { class: "sel-info" });
  root.replaceChildren(
    playBtn, clock,
    el("button", { title: "Set start (I)", onclick: () => setIn(player.getTime()) }, "Set In"),
    el("button", { title: "Set end (O)", onclick: () => setOut(player.getTime()) }, "Set Out"),
    el("button", { onclick: () => player.playSelection() }, "Play selection"),
    el("button", { class: "ghost", onclick: clearSelection }, "Clear selection"),
    selInfo,
  );

  const refresh = () => {
    const p = getProject();
    const total = p ? tm.editedDuration(p.clips) : 0;
    clock.textContent = `${fmtTime(player.getTime())} / ${fmtTime(total)}`;
    playBtn.textContent = player.isPlaying() ? "⏸ Pause" : "▶ Play";
    const s = p?.selection;
    selInfo.textContent = s ? `Selection ${fmtTime(s.start)} – ${fmtTime(s.end)} (${(s.end - s.start).toFixed(1)} s)` : "No selection";
  };
  player.onTime(refresh);
  subscribe(refresh);
  refresh();

  document.addEventListener("keydown", (e) => {
    if (e.target.matches("input, textarea, select, [contenteditable]")) return;
    if (e.code === "Space") (e.preventDefault(), player.toggle());
    else if (e.key === "i") setIn(player.getTime());
    else if (e.key === "o") setOut(player.getTime());
    else if (e.key === "ArrowLeft") player.seek(Math.max(0, player.getTime() - (e.shiftKey ? 5 : 1)));
    else if (e.key === "ArrowRight") player.seek(player.getTime() + (e.shiftKey ? 5 : 1));
  });
}
