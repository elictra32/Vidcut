// Logo / photo overlays: a panel to add and tune them, and draggable images on the preview stage.
// x/y/width are fractions of the frame, exactly as in the export (core/export.py overlay_statements).
import { api } from "./api.js";
import { flush, getProject, loadProject, subscribe, update } from "./state.js";
import { showError } from "./toast.js";
import { $, basename, el, numberSlider } from "./util.js";

const layer = $("#ov-layer");
const frame = $("#frame");
const nodes = new Map(); // overlay id -> <img>

const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));
const find = (q, id) => q.overlays.find((o) => o.id === id);

function renderStage() {
  const p = getProject();
  if (!p) return;
  const ids = new Set(p.overlays.map((o) => o.id));
  for (const [id, node] of nodes) if (!ids.has(id)) (node.remove(), nodes.delete(id));
  for (const o of p.overlays) {
    let node = nodes.get(o.id);
    if (!node) {
      node = el("img", { class: "ov", src: `/overlay-media/${o.id}`, alt: "Logo or photo overlay", draggable: "false",
        title: "Drag to move · mouse wheel to resize" });
      node.addEventListener("pointerdown", (e) => startDrag(e, o.id));
      node.addEventListener("wheel", (e) => {
        e.preventDefault();
        update((q) => { const t = find(q, o.id); t.width = +clamp(t.width * Math.exp(-e.deltaY * 0.001), 0.03, 1).toFixed(3); }, "ov-pos");
      }, { passive: false });
      layer.append(node);
      nodes.set(o.id, node);
    }
    Object.assign(node.style, { left: `${o.x * 100}%`, top: `${o.y * 100}%`, width: `${o.width * 100}%`, opacity: o.opacity });
  }
}

function startDrag(e, id) {
  const o = find(getProject(), id);
  const r = frame.getBoundingClientRect();
  const dx = (e.clientX - r.left) / r.width - o.x, dy = (e.clientY - r.top) / r.height - o.y;
  const node = e.currentTarget;
  node.setPointerCapture(e.pointerId);
  const move = (ev) => {
    const rect = frame.getBoundingClientRect();
    update((q) => {
      const t = find(q, id);
      t.x = +clamp((ev.clientX - rect.left) / rect.width - dx, 0, 1).toFixed(4);
      t.y = +clamp((ev.clientY - rect.top) / rect.height - dy, 0, 1).toFixed(4);
    }, "ov-pos");
  };
  const up = () => (node.removeEventListener("pointermove", move), node.removeEventListener("pointerup", up));
  node.addEventListener("pointermove", move);
  node.addEventListener("pointerup", up);
}

async function addImage() {
  try {
    if (!(await flush())) return;
    const r = await api("POST", "/api/overlays/pick");
    if (r.overlay) await loadProject();
  } catch (e) {
    showError(e);
  }
}

async function removeImage(id) {
  try {
    if (!(await flush())) return;
    await api("DELETE", `/api/overlays/${id}`);
    await loadProject();
  } catch (e) {
    showError(e);
  }
}

function slider(label, value, min, max, step, onInput) {
  const ns = numberSlider({ min, max, step, value, unit: "%", label: `${label} (percent)`, toDisplay: (v) => v * 100, fromDisplay: (d) => d / 100, onInput });
  return el("div", { class: "field" }, el("span", {}, label), ns.root);
}

function posBox(o, axis) {
  const input = el("input", { type: "number", class: "num", "data-axis": axis, min: 0, max: 100, step: 1, value: Math.round(o[axis] * 100), "aria-label": `${axis === "x" ? "Horizontal" : "Vertical"} position (percent)` });
  input.addEventListener("change", () => {
    const d = parseFloat(input.value);
    if (Number.isFinite(d)) update((q) => (find(q, o.id)[axis] = clamp(d / 100, 0, 1)), "ov-pos");
  });
  return input;
}

function seconds(value, onChange, aria) {
  const input = el("input", { type: "number", min: 0, step: 0.5, class: "ov-time", "aria-label": aria, value: value ?? "" });
  input.addEventListener("input", () => onChange(input.value === "" ? null : Math.max(0, parseFloat(input.value) || 0)));
  return input;
}

export function initOverlays() {
  const root = $("#overlay-panel");
  const list = el("div", { class: "ov-list" });
  root.replaceChildren(
    el("h2", {}, "Logo / photo"),
    el("button", { id: "btn-add-overlay", onclick: addImage }, "+ Add image"),
    el("p", { class: "muted small" }, "PNG with a transparent background works best. Drag it on the preview; use the mouse wheel to resize."),
    list);

  const renderList = () => {
    const p = getProject();
    if (!p) return;
    list.replaceChildren(...p.overlays.map((o) => el("div", { class: "ov-row", "data-id": o.id },
      el("div", { class: "row" }, el("img", { class: "ov-thumb", src: `/overlay-media/${o.id}`, alt: "" }),
        el("span", { class: "muted small ov-name" }, basename(o.path)), el("span", { class: "spacer" }),
        el("button", { class: "ghost icon", title: "Remove this image from the project", onclick: () => removeImage(o.id) }, "✕")),
      slider("Size", o.width, 0.03, 1, 0.01, (v) => update((q) => (find(q, o.id).width = v), "ov-pos")),
      slider("Opacity", o.opacity, 0.1, 1, 0.05, (v) => update((q) => (find(q, o.id).opacity = v), "ov-pos")),
      el("div", { class: "field" }, el("span", {}, "Position (percent of the frame)"),
        el("div", { class: "row" }, el("span", { class: "muted small" }, "X"), posBox(o, "x"), el("span", { class: "muted small" }, "Y"), posBox(o, "y"))),
      el("div", { class: "field" }, el("span", {}, "Show from / to (seconds in the exported video; empty = whole video)"),
        el("div", { class: "row" },
          seconds(o.start, (v) => update((q) => (find(q, o.id).start = v), "ov-time"), "Show from (seconds)"),
          seconds(o.end, (v) => update((q) => (find(q, o.id).end = v), "ov-time"), "Show until (seconds)"))))));
    if (!p.overlays.length) list.append(el("p", { class: "muted small" }, "No images yet."));
  };

  subscribe((why) => {
    renderStage();
    if (why === "load") renderList();
    else if (why === "ov-pos") {
      // a drag on the preview moved an image: show the new position in the boxes
      for (const row of list.querySelectorAll(".ov-row")) {
        const o = find(getProject(), row.dataset.id);
        for (const box of row.querySelectorAll("input[data-axis]")) if (o && document.activeElement !== box) box.value = String(Math.round(o[box.dataset.axis] * 100));
      }
    }
  });
  renderStage();
  renderList();
}
