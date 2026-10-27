export const $ = (sel, root = document) => root.querySelector(sel);

export function fmtTime(t) {
  if (!Number.isFinite(t) || t < 0) t = 0;
  const m = Math.floor(t / 60);
  return `${m}:${(t - m * 60).toFixed(1).padStart(4, "0")}`;
}

export const basename = (p) => p.split(/[\\/]/).pop();

/** Size a canvas to its CSS box at device resolution; returns a 2D ctx in CSS pixels. */
export function fitCanvas(canvas) {
  const r = canvas.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;
  const w = Math.max(1, Math.round(r.width * dpr));
  const h = Math.max(1, Math.round(r.height * dpr));
  if (canvas.width !== w || canvas.height !== h) {
    canvas.width = w;
    canvas.height = h;
  }
  const ctx = canvas.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  return { ctx, w: r.width, h: r.height };
}

export const cssVar = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

export function rafThrottle(fn) {
  let queued = false;
  return (...args) => {
    if (queued) return;
    queued = true;
    requestAnimationFrame(() => {
      queued = false;
      fn(...args);
    });
  };
}

export function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") node.className = v;
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else if (v !== false && v != null) node.setAttribute(k, v === true ? "" : v);
  }
  for (const c of children.flat()) node.append(c instanceof Node ? c : document.createTextNode(c ?? ""));
  return node;
}

export function remember(key, value) {
  try { localStorage.setItem(key, value); } catch { /* storage blocked: the choice just isn't remembered */ }
}
export function recall(key, fallback) {
  try { return localStorage.getItem(key) ?? fallback; } catch { return fallback; }
}


/**
 * A slider with a number box beside it, kept in step: drag for speed, type for precision.
 * `toDisplay`/`fromDisplay` convert between the stored value and what the box shows (e.g. 0.52 <-> 52 for percent).
 * Returns { root, sync(value), focused() }; `onInput(value)` gets the stored value.
 */
export function numberSlider({ min, max, step, value, toDisplay = (v) => v, fromDisplay = (d) => d, unit = "", onInput, label = "" }) {
  const range = el("input", { type: "range", min, max, step, value });
  const dMin = toDisplay(min), dMax = toDisplay(max);
  const num = el("input", { type: "number", class: "num", min: Math.min(dMin, dMax), max: Math.max(dMin, dMax),
    step: Math.abs(toDisplay(min + step) - dMin) || 1, "aria-label": label });
  const show = (v) => (num.value = String(Math.round(toDisplay(v) * 100) / 100));
  const sync = (v) => { range.value = v; show(v); };
  const clampStored = (v) => Math.min(max, Math.max(min, v));
  range.addEventListener("input", () => { show(parseFloat(range.value)); onInput(parseFloat(range.value)); });
  num.addEventListener("change", () => {
    const d = parseFloat(num.value);
    if (!Number.isFinite(d)) return show(parseFloat(range.value)); // not a number: put the old value back
    const v = clampStored(fromDisplay(d));
    sync(v);
    onInput(v);
  });
  sync(value);
  return { root: el("span", { class: "numslider" }, range, num, unit ? el("span", { class: "muted small" }, unit) : ""), sync,
    focused: () => document.activeElement === num || document.activeElement === range };
}
