// Browser-side port of core/timeline.py. Keep the two in step: tests/js runs the same
// fixture cases (tests/fixtures/timeline_cases.json) against this file.
// Source time = seconds in a clip's file. Edited time = enabled keeps of all clips, concatenated.
const EPS = 1e-9;

export const enabledKeeps = (clip) =>
  clip.keeps.filter((k) => k.enabled).sort((a, b) => a.start - b.start);

/** The clips on the edit timeline; intro/outro clips are joined around the selection at export. */
export const mainClips = (clips) => clips.filter((c) => (c.role ?? "main") === "main");

/** Every enabled keep in edited order, with where it starts on the edited axis. */
export function segments(clips) {
  const out = [];
  let t = 0;
  for (const c of mainClips(clips)) {
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
      const piece = { clipId: g.clipId, srcStart: g.keep.start + (lo - g.editedStart),
                      srcEnd: g.keep.start + (hi - g.editedStart), outStart: lo - sel.start };
      const last = out[out.length - 1];
      if (last && last.clipId === piece.clipId && Math.abs(last.srcEnd - piece.srcStart) < 1e-6) last.srcEnd = piece.srcEnd; // split, nothing removed
      else out.push(piece);
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

const MIN_SUB = 0.1;

/**
 * Dragging a subtitle edge to edited time `t` -> its new source anchor. An edge dragged into
 * a different clip clamps to this clip's nearest keep boundary; edges never cross.
 */
export function dragEdgeToSource(clips, sub, which, t) {
  const clip = clips.find((c) => c.id === sub.clip_id);
  const keeps = enabledKeeps(clip);
  const current = which === "start" ? sub.src_start : sub.src_end;
  if (!keeps.length) return current;
  const hit = which === "start" ? editedToSource(clips, t) : editedEndToSource(clips, t);
  let src = current;
  if (hit) {
    if (hit[0] === clip.id) src = hit[1];
    else {
      const order = clips.map((c) => c.id);
      src = order.indexOf(hit[0]) < order.indexOf(clip.id) ? keeps[0].start : keeps[keeps.length - 1].end;
    }
  }
  return which === "start" ? Math.min(src, sub.src_end - MIN_SUB) : Math.max(src, sub.src_start + MIN_SUB);
}

/**
 * What playback should do when the loaded clip is at source time `t`:
 * keep playing, seek past a removed gap, hop to the next clip with something kept, or end.
 */
export function nextPlayTarget(clips, clipId, t) {
  const i = clips.findIndex((c) => c.id === clipId);
  const keeps = enabledKeeps(clips[i]);
  if (keeps.some((k) => t >= k.start - 0.03 && t < k.end)) return { kind: "play" };
  const next = keeps.find((k) => k.start > t);
  if (next) return { kind: "seek", src: next.start };
  for (const c of mainClips(clips.slice(i + 1))) {
    const first = enabledKeeps(c)[0];
    if (first) return { kind: "clip", clipId: c.id, src: first.start };
  }
  return { kind: "end" };
}

/**
 * While playing at source time `t` of `clipId`: when the current kept segment ends (`at`, source
 * seconds) and what playback does then (same shape as nextPlayTarget). Null when `t` is not inside a
 * kept segment. The player uses it to prepare the next position before the cut arrives.
 */
export function upcomingBoundary(clips, clipId, t) {
  const clip = clips.find((c) => c.id === clipId);
  const keep = clip && enabledKeeps(clip).find((k) => t >= k.start - 0.03 && t < k.end);
  return keep ? { at: keep.end, target: nextPlayTarget(clips, clipId, keep.end) } : null;
}
