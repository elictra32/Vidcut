import { api, ApiError } from "./api.js";
import { showError, showToast } from "./toast.js";
import { remapSelection } from "./timeline_math.js";

let project = null;
let presets = {};
let fonts = [];
let saveTimer = null;
let dirty = false;
let inflight = null; // the save currently on its way to the server
const listeners = new Set();

/** Transient UI state (not saved). */
export const ui = { currentClipId: null, selectedSubId: null };

export const getProject = () => project;
export const getPresets = () => presets;
export const getFonts = () => fonts;
export const subscribe = (fn) => (listeners.add(fn), () => listeners.delete(fn));
const notify = (why) => listeners.forEach((f) => f(why));

// ---- undo / redo ------------------------------------------------------------------------------------
// A snapshot holds what the PAGE owns (see PUT /api/project): cut keeps, framing, roles, subtitles, style, selection,
// overlay placement, export options. Media files and the server's own bookkeeping are never restored.
const MAX_HISTORY = 100;
const GROUP_MS = 800; // edits of one kind this close together (typing, dragging a slider) undo as one step
const undoStack = [];
const redoStack = [];
let lastEdit = { why: null, at: 0 };

const snapshot = () => project && structuredClone({
  clips: project.clips.map((c) => ({ id: c.id, keeps: c.keeps, framing: c.framing, role: c.role, cuts_confirmed: c.cuts_confirmed })),
  subtitles: project.subtitles, style: project.style, selection: project.selection, preset: project.preset,
  overlays: project.overlays, export: { container: project.export.container, quality: project.export.quality, target_mb: project.export.target_mb },
});

function pushUndo(snap) {
  if (!snap) return;
  undoStack.push(snap);
  if (undoStack.length > MAX_HISTORY) undoStack.shift();
  redoStack.length = 0;
  notify("history");
}

function restore(snap) {
  for (const s of snap.clips) {
    const c = project.clips.find((x) => x.id === s.id);
    if (c) Object.assign(c, { keeps: s.keeps, framing: s.framing, role: s.role, cuts_confirmed: s.cuts_confirmed });
  }
  const ids = new Set(project.clips.map((c) => c.id));
  project.subtitles = snap.subtitles.filter((s) => ids.has(s.clip_id));
  project.style = snap.style;
  project.selection = snap.selection;
  project.preset = snap.preset;
  for (const o of snap.overlays) {
    const cur = project.overlays.find((x) => x.id === o.id);
    if (cur) Object.assign(cur, { x: o.x, y: o.y, width: o.width, opacity: o.opacity, start: o.start, end: o.end });
  }
  Object.assign(project.export, snap.export);
  lastEdit = { why: null, at: 0 };
  notify("undo");
  dirty = true;
  clearTimeout(saveTimer);
  saveTimer = setTimeout(() => flush().catch(() => {}), 400);
}

export const canUndo = () => undoStack.length > 0;
export const canRedo = () => redoStack.length > 0;

export function undo() {
  if (!undoStack.length) return false;
  redoStack.push(snapshot());
  restore(undoStack.pop());
  notify("history");
  return true;
}

export function redo() {
  if (!redoStack.length) return false;
  undoStack.push(snapshot());
  restore(redoStack.pop());
  notify("history");
  return true;
}

export async function loadProject() {
  const before = snapshot();
  const r = await api("GET", "/api/project");
  project = r.project;
  // something changed on the server (a finished job, an import): make that undoable too
  if (before && JSON.stringify(before) !== JSON.stringify(snapshot())) {
    undoStack.push(before);
    if (undoStack.length > MAX_HISTORY) undoStack.shift();
    redoStack.length = 0;
  }
  presets = r.presets ?? {};
  fonts = r.fonts ?? [];
  if (!project.clips.some((c) => c.id === ui.currentClipId)) ui.currentClipId = project.clips[0]?.id ?? null;
  notify("load");
}

/** Mutate the project in place, notify, and save (debounced). */
export function update(mutator, why = "edit") {
  const now = Date.now();
  if (why !== "select" && why !== "ui" && (why !== lastEdit.why || now - lastEdit.at > GROUP_MS)) pushUndo(snapshot());
  lastEdit = { why, at: now };
  mutator(project);
  notify(why);
  dirty = true;
  clearTimeout(saveTimer);
  saveTimer = setTimeout(() => flush().catch(() => {}), 400);
}

/** Change keeps while keeping the selection on the same source content. */
export function updateKeeps(mutator) {
  const before = structuredClone(project.clips);
  update((p) => {
    mutator(p);
    p.selection = remapSelection(before, p.clips, p.selection);
  }, "keeps");
}

/** One PUT of the current project. Resolves true when the server stored it. */
async function saveOnce() {
  dirty = false;
  try {
    await api("PUT", "/api/project", project);
    return true;
  } catch (e) {
    if (e.payload?.code === "project_stale") {
      // a background job finished since this page last loaded: take the server's version, never overwrite it
      await loadProject();
      showToast("A background job just finished and the latest data was reloaded. You may need to redo your most recent edit", "error", 7000);
      return false;
    }
    dirty = true; // keep it: the next flush retries
    showError(e);
    return false;
  }
}

/**
 * Resolve true once the server holds every edit made so far, waiting for a save that is already in
 * flight and for edits made meanwhile; false when it could not be saved. Anything that asks the server
 * to act on the project must stop on false, or it would work on stale data.
 */
export async function flush() {
  clearTimeout(saveTimer);
  for (;;) {
    if (inflight) {
      if (!(await inflight)) return false;
      continue;
    }
    if (!dirty) return true;
    inflight = saveOnce().finally(() => (inflight = null));
    if (!(await inflight)) return false;
  }
}

/** Save again even though nothing looks changed (used when the server turns out to be out of step). */
export function forceSave() {
  dirty = true;
  return flush();
}

export const saveFailed = () => new ApiError({
  code: "save_failed", message: "Couldn't save your latest edit",
  hint: "Check that the black run.bat window is still open, then try again" }, 0);

/**
 * Run a server call that acts on the SAVED project (transcribe, export, import...). Saves first; and when
 * the server says there is no selection although this page has one, a save was lost somewhere: re-send
 * the project and retry once instead of showing a confusing error.
 */
export async function withSavedProject(call) {
  if (!(await flush())) throw saveFailed();
  try {
    return await call();
  } catch (e) {
    if (e.payload?.code === "no_selection" && project?.selection) {
      if (!(await forceSave())) throw saveFailed();
      return await call();
    }
    throw e;
  }
}

/** After a server-side job changed the project: save pending edits, then re-fetch. */
export async function reloadAfterJob(keepSelectionFrom = null) {
  await flush();
  await loadProject();
  if (keepSelectionFrom) {
    update((p) => (p.selection = remapSelection(keepSelectionFrom, p.clips, p.selection)), "keeps");
  }
}

export function setCurrentClip(id) {
  ui.currentClipId = id;
  notify("clip");
}

export function setSelectedSub(id) {
  ui.selectedSubId = id;
  notify("select");
}

/** Change transient UI state (not saved with the project). */
export function setUi(patch, why = "ui") {
  Object.assign(ui, patch);
  notify(why);
}
