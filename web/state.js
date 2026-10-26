import { api } from "./api.js";
import { showError } from "./toast.js";
import { remapSelection } from "./timeline_math.js";

let project = null;
let presets = {};
let saveTimer = null;
let dirty = false;
const listeners = new Set();

/** Transient UI state (not saved). */
export const ui = { currentClipId: null, selectedSubId: null };

export const getProject = () => project;
export const getPresets = () => presets;
export const subscribe = (fn) => (listeners.add(fn), () => listeners.delete(fn));
const notify = (why) => listeners.forEach((f) => f(why));

export async function loadProject() {
  const r = await api("GET", "/api/project");
  project = r.project;
  presets = r.presets ?? {};
  if (!project.clips.some((c) => c.id === ui.currentClipId)) ui.currentClipId = project.clips[0]?.id ?? null;
  notify("load");
}

/** Mutate the project in place, notify, and save (debounced). */
export function update(mutator, why = "edit") {
  mutator(project);
  notify(why);
  dirty = true;
  clearTimeout(saveTimer);
  saveTimer = setTimeout(flush, 400);
}

/** Change keeps while keeping the selection on the same source content. */
export function updateKeeps(mutator) {
  const before = structuredClone(project.clips);
  update((p) => {
    mutator(p);
    p.selection = remapSelection(before, p.clips, p.selection);
  }, "keeps");
}

export async function flush() {
  clearTimeout(saveTimer);
  if (!dirty) return;
  dirty = false;
  try {
    await api("PUT", "/api/project", project);
  } catch (e) {
    dirty = true;
    showError(e);
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
