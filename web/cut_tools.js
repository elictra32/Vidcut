// Cutting straight on the edit timeline: split at the playhead, delete the segment under it, or cut out In-Out.
import { getProject, updateKeeps } from "./state.js";
import * as player from "./player.js";
import * as tm from "./timeline_math.js";
import { showToast } from "./toast.js";
import { deleteKeepAt, removeRange, splitKeeps } from "./cut_ops.js";

function apply(clipId, keeps, done) {
  updateKeeps((p) => { p.clips.find((c) => c.id === clipId).keeps = keeps; });
  if (done) showToast(done, "info", 2500);
}

/** Split the segment under the playhead in two. */
export function cutHere() {
  const p = getProject();
  const hit = p && tm.editedToSource(p.clips, player.getTime());
  if (!hit) return showToast("Add a clip first", "error");
  const keeps = splitKeeps(p.clips.find((c) => c.id === hit[0]).keeps, hit[1]);
  if (!keeps) return showToast("Move the playhead inside a kept segment (not at its very edge) to cut there", "error", 4000);
  apply(hit[0], keeps, "Cut. Now delete the part you don't want (Delete key).");
}

/** Take the whole segment under the playhead out of the edit. */
export function deleteSegment() {
  const p = getProject();
  const hit = p && tm.editedToSource(p.clips, player.getTime());
  if (!hit) return showToast("Add a clip first", "error");
  const keeps = deleteKeepAt(p.clips.find((c) => c.id === hit[0]).keeps, hit[1]);
  if (!keeps) return showToast("Nothing to delete at the playhead", "error");
  apply(hit[0], keeps, "Deleted. Ctrl+Z brings it back.");
}

/** Cut out everything between In and Out. */
export function cutOutSelection() {
  const p = getProject();
  if (!p?.selection) return showToast("Set In and Out first", "error");
  let pieces;
  try { pieces = tm.selectionPieces(p.clips, p.selection); } catch { return showToast("The In/Out range is not valid", "error"); }
  const edits = new Map();
  for (const piece of pieces) {
    const base = edits.get(piece.clipId) ?? p.clips.find((c) => c.id === piece.clipId).keeps;
    const next = removeRange(base, piece.srcStart, piece.srcEnd);
    if (next) edits.set(piece.clipId, next);
  }
  if (!edits.size) return showToast("Nothing to cut out in that range", "error");
  updateKeeps((q) => { for (const [id, keeps] of edits) q.clips.find((c) => c.id === id).keeps = keeps; });
  showToast("Cut out the selected range. Ctrl+Z brings it back.", "info", 3000);
}
