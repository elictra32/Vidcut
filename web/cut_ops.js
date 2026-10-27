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

/** Keep only the source ranges `ranges` ([{start,end}]): enabled parts outside them become disabled keeps (restorable). */
export function keepOnly(keeps, ranges) {
  const rs = ranges.filter((r) => r.end - r.start > MIN_PART).sort((a, b) => a.start - b.start);
  const out = [];
  for (const k of keeps) {
    if (!k.enabled) { out.push({ ...k }); continue; }
    let at = k.start;
    for (const r of rs) {
      const a = Math.max(r.start, k.start), b = Math.min(r.end, k.end);
      if (b - a <= 1e-9) continue;
      if (a - at > 1e-9) out.push({ start: at, end: a, enabled: false });
      out.push({ start: a, end: b, enabled: true });
      at = b;
    }
    if (k.end - at > 1e-9) out.push({ start: at, end: k.end, enabled: false });
  }
  return out.sort(byStart);
}
