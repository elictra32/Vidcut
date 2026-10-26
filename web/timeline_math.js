// Browser-side port of core/timeline.py. Keep the two in step: tests/js runs the same
// fixture cases (tests/fixtures/timeline_cases.json) against this file.
// Source time = seconds in a clip's file. Edited time = enabled keeps of all clips, concatenated.
const EPS = 1e-9;

export const enabledKeeps = (clip) =>
  clip.keeps.filter((k) => k.enabled).sort((a, b) => a.start - b.start);

/** Every enabled keep in edited order, with where it starts on the edited axis. */
export function segments(clips) {
  const out = [];
  let t = 0;
  for (const c of clips) {
    for (const k of enabledKeeps(c)) {
      out.push({ clipId: c.id, keep: k, editedStart: t, len: k.end - k.start });
      t += k.end - k.start;
    }
  }
  return out;
}

export const editedDuration = (clips) => segments(clips).reduce((s, g) => s + g.len, 0);

export function sourceToEdited(clips, clipId, t) {
  for (const g of segments(clips)) {
    if (g.clipId === clipId && g.keep.start - EPS <= t && t <= g.keep.end + EPS) {
      return g.editedStart + (t - g.keep.start);
    }
  }
  return null;
}

export function editedToSource(clips, t) {
  const segs = segments(clips);
  if (!segs.length) return null;
  for (const g of segs) {
    if (t < g.editedStart + g.len - EPS) return [g.clipId, g.keep.start + Math.max(0, t - g.editedStart)];
  }
  const last = segs[segs.length - 1];
  return [last.clipId, last.keep.end];
}

/** Like editedToSource, but for an END time: a boundary belongs to the segment that ends there. */
export function editedEndToSource(clips, t) {
  const segs = segments(clips);
  if (!segs.length) return null;
  let hit = segs[0];
  for (const g of segs) if (g.editedStart < t - EPS) hit = g;
  return [hit.clipId, hit.keep.start + Math.min(Math.max(0, t - hit.editedStart), hit.len)];
}

export function clampToKeep(clips, clipId, t) {
  const clip = clips.find((c) => c.id === clipId);
  const keeps = enabledKeeps(clip);
  if (!keeps.length) return t;
  if (keeps.some((k) => k.start <= t && t <= k.end)) return t;
  const bounds = keeps.flatMap((k) => [k.start, k.end]);
  return bounds.reduce((best, b) => {
    const d = Math.abs(b - t), bd = Math.abs(best - t);
    return d < bd || (d === bd && b < best) ? b : best;
  });
}

export function selectionPieces(clips, sel) {
  const total = editedDuration(clips);
  if (total <= 0 || sel.start < 0 || sel.start >= sel.end || sel.end > total + 1e-6) {
    throw new Error("selection_invalid");
  }
  const out = [];
  for (const g of segments(clips)) {
    const lo = Math.max(sel.start, g.editedStart);
    const hi = Math.min(sel.end, g.editedStart + g.len);
    if (hi - lo > EPS) {
      out.push({ clipId: g.clipId, srcStart: g.keep.start + (lo - g.editedStart),
                 srcEnd: g.keep.start + (hi - g.editedStart), outStart: lo - sel.start });
    }
  }
  return out;
}

/** Edited-time span of a source-anchored subtitle, or null when it lies wholly in cut regions. */
export function subtitleEditedSpan(clips, sub) {
  const clip = clips.find((c) => c.id === sub.clip_id);
  if (!clip) return null;
  const keeps = enabledKeeps(clip);
  const first = keeps.find((k) => k.end > sub.src_start + EPS);
  const last = [...keeps].reverse().find((k) => k.start < sub.src_end - EPS);
  if (!first || !last) return null;
  const start = Math.max(sub.src_start, first.start);
  const end = Math.min(sub.src_end, last.end);
  if (end - start <= EPS) return null;
  const es = sourceToEdited(clips, clip.id, start);
  const ee = sourceToEdited(clips, clip.id, end);
  if (es === null || ee === null || ee - es <= EPS) return null;
  return [es, ee];
}

/** Keep the selection on the same source content after the keeps changed. */
export function remapSelection(oldClips, newClips, sel) {
  if (!sel || !segments(newClips).length || !segments(oldClips).length) return null;
  const toEdited = ([clipId, t]) => {
    const e = sourceToEdited(newClips, clipId, t);
    return e !== null ? e : sourceToEdited(newClips, clipId, clampToKeep(newClips, clipId, t));
  };
  const start = toEdited(editedToSource(oldClips, sel.start));
  const end = toEdited(editedEndToSource(oldClips, sel.end));
  if (start === null || end === null || end - start < 0.05) return null;
  return { start, end };
}
