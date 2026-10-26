// The preview stage: a frame with the EXPORT's aspect ratio (from the preset), the video
// framed the way export will frame it, and the subtitles drawn over it in CSS.
// Subtitle x/y are fractions of this frame, exactly as in the ASS export.
import { getPresets, getProject, setSelectedSub, subscribe, ui, update } from "./state.js";
import * as player from "./player.js";
import * as tm from "./timeline_math.js";
import { $ } from "./util.js";

const stage = $("#stage");
const frame = $("#frame");
const videos = [...document.querySelectorAll("#frame video")]; // two: see player.js
const overlay = $("#sub-overlay");
const safeZone = $("#safe-zone");
const nodes = new Map(); // subtitle id -> element
let drag = null;
let cropDrag = null;

const preset = () => getPresets()[getProject()?.preset] ?? { width: 1080, height: 1920 };

function layout() {
  const pr = preset();
  const r = stage.getBoundingClientRect();
  const k = Math.min(r.width / pr.width, r.height / pr.height);
  if (!(k > 0)) return;
  frame.style.width = `${pr.width * k}px`;
  frame.style.height = `${pr.height * k}px`;
  const p = getProject();
  const clip = p?.clips.find((c) => c.id === (player.getLoadedClipId() ?? ui.currentClipId));
  const sameAspect = clip && Math.abs(clip.width / clip.height - pr.width / pr.height) < 0.01;
  if (clip && clip.framing.mode === "crop" && !sameAspect) {
    for (const v of videos) Object.assign(v.style, { objectFit: "cover", objectPosition: `${clip.framing.crop_center_x * 100}% 50%` });
  } else {
    for (const v of videos) Object.assign(v.style, { objectFit: "contain", objectPosition: "50% 50%" });
  }
  const sz = getPresets()[p?.preset]?.safe_zone;
  safeZone.style.display = ui.showSafeZone && sz ? "block" : "none";
  if (sz) Object.assign(safeZone.style, { top: `${sz.top * 100}%`, bottom: `${sz.bottom * 100}%`, left: `${sz.left * 100}%`, right: `${sz.right * 100}%` });
  frame.style.cursor = cropAxis(clip, pr) ? "ew-resize" : "default";
  render();
}

/** Horizontal overflow (px) of the covered video when cropping, else 0. */
function cropOverflow(clip, pr) {
  if (!clip || clip.framing.mode !== "crop") return 0;
  return Math.max(0, frame.clientHeight * (clip.width / clip.height) - frame.clientWidth);
}
const cropAxis = (clip, pr) => cropOverflow(clip, pr) > 1;

function style(node, sub, st, scale) {
  const box = st.bg_color != null;
  Object.assign(node.style, {
    left: `${(sub.x ?? st.default_x) * 100}%`,
    top: `${(sub.y ?? st.default_y) * 100}%`,
    fontSize: `${st.size * scale}px`,
    fontFamily: `"${st.font}", "Leelawadee UI", sans-serif`,
    color: st.color,
    webkitTextStroke: box || !st.outline_width ? "0" : `${st.outline_width * 2 * scale}px ${st.outline_color}`,
    paintOrder: "stroke fill",
    textShadow: st.shadow ? `${st.shadow * scale}px ${st.shadow * scale}px 0 rgba(0,0,0,.5)` : "none",
    background: box ? st.bg_color : "transparent",
    padding: box ? `${Math.max(2, st.outline_width * scale)}px ${Math.max(4, st.outline_width * 2 * scale)}px` : "0",
  });
  node.textContent = sub.text;
  node.classList.toggle("selected", sub.id === ui.selectedSubId);
}

function render() {
  const p = getProject();
  if (!p || !frame.clientWidth) return;
  const t = player.getTime();
  const scale = frame.clientWidth / preset().width;
  const active = p.subtitles.filter((s) => {
    const span = tm.subtitleEditedSpan(p.clips, s);
    return span && t >= span[0] - 1e-6 && t < span[1];
  });
  const keep = new Set(active.map((s) => s.id));
  for (const [id, node] of nodes) if (!keep.has(id)) (node.remove(), nodes.delete(id));
  for (const sub of active) {
    let node = nodes.get(sub.id);
    if (!node) {
      node = document.createElement("div");
      node.className = "sub";
      node.addEventListener("pointerdown", (e) => startDrag(e, sub.id));
      node.addEventListener("dblclick", () => update((q) => {
        const s = q.subtitles.find((x) => x.id === sub.id);
        s.x = s.y = null;
      }, "subs-pos"));
      overlay.append(node);
      nodes.set(sub.id, node);
    }
    style(node, sub, p.style, scale);
  }
}

function startDrag(e, id) {
  const p = getProject();
  const sub = p.subtitles.find((s) => s.id === id);
  const r = frame.getBoundingClientRect();
  e.currentTarget.setPointerCapture(e.pointerId);
  setSelectedSub(id);
  drag = {
    id,
    dx: (e.clientX - r.left) / r.width - (sub.x ?? p.style.default_x),
    dy: (e.clientY - r.top) / r.height - (sub.y ?? p.style.default_y),
    node: e.currentTarget,
  };
  const move = (ev) => {
    const rect = frame.getBoundingClientRect();
    const x = Math.min(1, Math.max(0, (ev.clientX - rect.left) / rect.width - drag.dx));
    const y = Math.min(1, Math.max(0, (ev.clientY - rect.top) / rect.height - drag.dy));
    update((q) => {
      const s = q.subtitles.find((z) => z.id === id);
      s.x = +x.toFixed(4);
      s.y = +y.toFixed(4);
    }, "subs-pos");
  };
  const up = () => {
    drag.node.removeEventListener("pointermove", move);
    drag.node.removeEventListener("pointerup", up);
    drag = null;
  };
  drag.node.addEventListener("pointermove", move);
  drag.node.addEventListener("pointerup", up);
}

function startCrop(e) {
  if (e.target.closest(".sub")) return;
  const p = getProject();
  const clip = p?.clips.find((c) => c.id === (player.getLoadedClipId() ?? ui.currentClipId));
  const overflow = cropOverflow(clip, preset());
  if (!clip || overflow <= 1) return;
  frame.setPointerCapture(e.pointerId);
  cropDrag = { x: e.clientX, cx: clip.framing.crop_center_x, overflow, clip };
}

function moveCrop(e) {
  if (!cropDrag) return;
  const cx = Math.min(1, Math.max(0, cropDrag.cx - (e.clientX - cropDrag.x) / cropDrag.overflow));
  update(() => (cropDrag.clip.framing.crop_center_x = +cx.toFixed(3)), "framing");
}

export function initStage() {
  ui.showSafeZone = true;
  frame.addEventListener("pointerdown", startCrop);
  frame.addEventListener("pointermove", moveCrop);
  frame.addEventListener("pointerup", () => (cropDrag = null));
  subscribe(layout);
  player.onTime(render);
  new ResizeObserver(layout).observe(stage);
  for (const v of videos) v.addEventListener("loadedmetadata", layout);
}
