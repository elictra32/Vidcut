// Pure editing operations on a clip's keeps (source seconds); the UI in cut_tools.js applies them.
const MIN_PART = 0.05; // never leave a sliver shorter than this

const byStart = (a, b) => a.start - b.start;

/** Split the enabled keep around source time `t` in two (nothing is removed). Null when `t` is not inside one. */
export function splitKeeps(keeps, t) {
  const i = keeps.findIndex((k) => k.enabled && t > k.start + MIN_PART && t < k.end - MIN_PART);
  if (i < 0) return null;
  const k = keeps[i];
  const out = keeps.map((x) => ({ ...x }));
  out.splice(i, 1, { start: k.start, end: t, enabled: true }, { start: t, end: k.end, enabled: true });
  return out;
}

/** Take the enabled keep that contains source time `t` out of the edit (it stays in the list, disabled). */
export function deleteKeepAt(keeps, t) {
  const i = keeps.findIndex((k) => k.enabled && t >= k.start && t < k.end);
  if (i < 0) return null;
  return keeps.map((x, j) => (j === i ? { ...x, enabled: false } : { ...x }));
}

/** Remove the source range [a, b): the parts of enabled keeps inside it become disabled keeps. */
export function removeRange(keeps, a, b) {
  if (!(b - a > MIN_PART)) return null;
  const out = [];
  let touched = false;
  for (const k of keeps) {
    if (!k.enabled || k.end <= a + 1e-9 || k.start >= b - 1e-9) { out.push({ ...k }); continue; }
    touched = true;
    if (k.start < a - 1e-9) out.push({ start: k.start, end: a, enabled: true });
    out.push({ start: Math.max(k.start, a), end: Math.min(k.end, b), enabled: false });
    if (k.end > b + 1e-9) out.push({ start: b, end: k.end, enabled: true });
  }
  return touched ? out.sort(byStart) : null;
}
