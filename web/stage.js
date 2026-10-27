// The preview stage: a frame with the EXPORT's aspect ratio (from the preset), the video
// framed the way export will frame it, and the subtitles drawn over it in CSS.
// Subtitle x/y are fractions of this frame, exactly as in the ASS export.
import { getPresets, getProject, setSelectedSub, subscribe, ui, update } from "./state.js";
import * as player from "./player.js";
import * as tm from "./timeline_math.js";
import { revealedCount } from "./reveal.js";
import { $, el } from "./util.js";

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

function style(node, sub, st, scale, span, t) {
  const box = st.bg_color != null;
  Object.assign(node.style, {
    left: `${(sub.x ?? st.default_x) * 100}%`,
    top: `${(sub.y ?? st.default_y) * 100}%`,
    fontSize: `${st.size * scale * (sub.scale ?? 1)}px`,
    fontFamily: `"${st.font}", "Leelawadee UI", sans-serif`,
    color: st.color,
    webkitTextStroke: box || !st.outline_width ? "0" : `${st.outline_width * 2 * scale}px ${st.outline_color}`,
    paintOrder: "stroke fill",
    textShadow: st.shadow ? `${st.shadow * scale}px ${st.shadow * scale}px 0 rgba(0,0,0,.5)` : "none",
    background: box ? st.bg_color : "transparent",
    padding: box ? `${Math.max(2, st.outline_width * scale)}px ${Math.max(4, st.outline_width * 2 * scale)}px` : "0",
  });
  if (st.reveal && span) {
    // the unspoken rest stays in the text (invisible) so the line keeps the position it will have when complete
    const chars = Array.from(sub.text), n = revealedCount(sub.text, span[0], span[1], t);
    const hidden = el("span", {}, chars.slice(n).join(""));
    hidden.style.visibility = "hidden";
    node.replaceChildren(chars.slice(0, n).join(""), hidden);
  } else {
    node.textContent = sub.text;
  }
  node.classList.toggle("selected", sub.id === ui.selectedSubId);
}

function render() {
  const p = getProject();
  if (!p || !frame.clientWidth) return;
  const t = player.getTime();
  const scale = frame.clientWidth / preset().width;
  const spans = new Map();
  const active = p.subtitles.filter((s) => {
    const span = tm.subtitleEditedSpan(p.clips, s);
    if (span) spans.set(s.id, span);
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
      node.addEventListener("dblclick", () => startEdit(node, sub.id));
      node.addEventListener("wheel", (e) => {
        e.preventDefault(); // wheel over a subtitle resizes just that line
        const f = Math.exp(-e.deltaY * 0.001);
        update((q) => {
          const s = q.subtitles.find((x) => x.id === sub.id);
          s.scale = +Math.min(3, Math.max(0.4, (s.scale ?? 1) * f)).toFixed(3);
        }, "subs-pos");
      }, { passive: false });
      overlay.append(node);
      nodes.set(sub.id, node);
    }
    if (node.dataset.editing) continue; // being typed in: leave its text alone
    style(node, sub, p.style, scale, spans.get(sub.id), t);
  }
}

/** Edit a subtitle's text right on the preview: Esc, Ctrl+Enter or clicking elsewhere saves; Enter adds a line break. */
function startEdit(node, id) {
  const sub = getProject().subtitles.find((s) => s.id === id);
  if (!sub || node.dataset.editing) return;
  player.pause();
  setSelectedSub(id);
  node.dataset.editing = "1";
  node.textContent = sub.text;
  node.contentEditable = "plaintext-only";
  if (node.contentEditable !== "plaintext-only") node.contentEditable = "true";
  node.focus();
  getSelection().selectAllChildren(node);
  const done = () => {
    node.removeEventListener("blur", done);
    node.removeEventListener("keydown", keys);
    const text = node.innerText.replace(/\u00a0/g, " ").replace(/\n+$/, "");
    node.contentEditable = "false";
    delete node.dataset.editing;
    if (text.trim() && text !== sub.text) update((q) => (q.subtitles.find((s) => s.id === id).text = text), "subs");
    else render();
  };
  const keys = (e) => {
    if (e.key === "Escape" || (e.key === "Enter" && (e.ctrlKey || e.metaKey))) { e.preventDefault(); node.blur(); }
    e.stopPropagation(); // typing must not trigger the app's shortcuts (space = play, I/O = In/Out ...)
  };
  node.addEventListener("blur", done);
  node.addEventListener("keydown", keys);
}

function startDrag(e, id) {
  if (e.currentTarget.dataset.editing) return; // text editing: let the click place the cursor
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
  if (e.target.closest(".sub, .ov")) return;
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
