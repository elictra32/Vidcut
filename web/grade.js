// Colour correction of a clip for the preview: the same numbers as core/grade.py, turned into an SVG colour matrix
// that is applied to the <video> as a CSS filter (tests/fixtures/grade_cases.json keeps the two in step).
const LIMIT = 100;
const clamp = (v) => Math.max(-LIMIT, Math.min(LIMIT, Number(v) || 0));

export const NEUTRAL = { temperature: 0, tint: 0, brightness: 0, contrast: 0, saturation: 0 };
export const isNeutral = (g) => !g || Object.keys(NEUTRAL).every((k) => Math.abs(g[k] ?? 0) < 1e-9);

export function gradeParams(g) {
  const t = clamp(g?.temperature), n = clamp(g?.tint);
  return { r: 1 + 0.30 * t / LIMIT, g: 1 - 0.25 * n / LIMIT, b: 1 - 0.30 * t / LIMIT,
    brightness: 0.25 * clamp(g?.brightness) / LIMIT, contrast: 1 + 0.5 * clamp(g?.contrast) / LIMIT, saturation: 1 + clamp(g?.saturation) / LIMIT };
}

/** 4x5 feColorMatrix values: channel gains, then saturation (BT.601 luma), then contrast around mid grey and brightness. */
export function gradeMatrix(g) {
  const p = gradeParams(g);
  const gain = [p.r, p.g, p.b];
  const W = [0.299, 0.587, 0.114];
  const rows = [];
  for (let i = 0; i < 3; i++) {
    const row = [];
    for (let j = 0; j < 3; j++) {
      const sat = (i === j ? p.saturation : 0) + (1 - p.saturation) * W[j];
      row.push(p.contrast * sat * gain[j]);
    }
    rows.push([...row, 0, 0.5 * (1 - p.contrast) + p.brightness]);
  }
  rows.push([0, 0, 0, 1, 0]);
  return rows.flat();
}

const SVG = "http://www.w3.org/2000/svg";
let defs = null;

function filterFor(id) {
  if (!defs) {
    const svg = document.createElementNS(SVG, "svg");
    svg.setAttribute("width", "0"); svg.setAttribute("height", "0"); svg.style.position = "absolute";
    defs = document.createElementNS(SVG, "defs");
    svg.append(defs);
    document.body.append(svg);
  }
  let f = defs.querySelector(`#${id}`);
  if (!f) {
    f = document.createElementNS(SVG, "filter");
    f.id = id;
    f.setAttribute("color-interpolation-filters", "sRGB");
    const m = document.createElementNS(SVG, "feColorMatrix");
    m.setAttribute("type", "matrix");
    f.append(m);
    defs.append(f);
  }
  return f.firstChild;
}

/** Show `clip`'s grade on the <video> element `video` (no filter at all when the grade is neutral). */
export function applyGrade(video, clip) {
  if (!video) return;
  const g = clip?.grade;
  if (isNeutral(g)) { video.style.filter = ""; return; }
  filterFor(`grade-${video.id}`).setAttribute("values", gradeMatrix(g).map((v) => +v.toFixed(5)).join(" "));
  video.style.filter = `url(#grade-${video.id})`;
}
