// Colour correction of a clip for the preview: the same numbers as core/grade.py, turned into an SVG colour matrix
// that is applied to the <video> as a CSS filter (tests/fixtures/grade_cases.json keeps the two in step).
const LIMIT = 100;
const BRIGHT_SCALE = 255 / 219; // eq brightness is in full-range code values, the picture is limited range
const clamp = (v) => Math.max(-LIMIT, Math.min(LIMIT, Number(v) || 0));

export const NEUTRAL = { temperature: 0, tint: 0, brightness: 0, contrast: 0, saturation: 0 };
export const isNeutral = (g) => !g || Object.keys(NEUTRAL).every((k) => Math.abs(g[k] ?? 0) < 1e-9);

export function gradeParams(g) {
  const t = clamp(g?.temperature), n = clamp(g?.tint);
  return { r: 1 + 0.30 * t / LIMIT, g: 1 - 0.25 * n / LIMIT, b: 1 - 0.30 * t / LIMIT,
    brightness: 0.25 * clamp(g?.brightness) / LIMIT, contrast: 1 + 0.5 * clamp(g?.contrast) / LIMIT, saturation: 1 + clamp(g?.saturation) / LIMIT };
}

/**
 * 4x5 feColorMatrix values. Same order as the export: channel gains, saturation (chroma only, luma kept), then contrast
 * and brightness on the LUMA only around mid grey (ffmpeg eq works on Y and chroma, not on R, G, B separately).
 */
const LUMA = { bt709: [0.2126, 0.7152, 0.0722], bt601: [0.299, 0.587, 0.114], bt2020: [0.2627, 0.678, 0.0593] };
/** `clip` (optional) tells which luma weights and range the picture uses; without it HD is assumed. */
export function gradeMatrix(g, clip = null) {
  const p = gradeParams(g);
  const m = clip?.color_matrix || ((clip?.height ?? 1080) >= 720 ? "bt709" : "bt601");
  const gain = [p.r, p.g, p.b];
  const W = LUMA[m] ?? LUMA.bt709;
  const bright = clip?.full_range ? 1 : BRIGHT_SCALE;
  const luma = W.map((w, j) => w * gain[j]); // luma after the gains; saturation keeps it
  const rows = [];
  for (let i = 0; i < 3; i++) {
    const row = [];
    for (let j = 0; j < 3; j++) {
      const sat = (i === j ? p.saturation : 0) + (1 - p.saturation) * W[j];
      row.push(sat * gain[j] + (p.contrast - 1) * luma[j]);
    }
    rows.push([...row, 0, p.brightness * bright - 0.5 * (p.contrast - 1)]);
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
  filterFor(`grade-${video.id}`).setAttribute("values", gradeMatrix(g, clip).map((v) => +v.toFixed(5)).join(" "));
  video.style.filter = `url(#grade-${video.id})`;
}
