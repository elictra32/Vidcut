// Plays the project in EDITED time: the <video> shows one clip at a time and playback
// skips over disabled keeps / dead-air gaps, jumping to the next clip when one ends.
import { getProject, subscribe, ui, setCurrentClip } from "./state.js";
import * as tm from "./timeline_math.js";
import { showError } from "./toast.js";
import { $ } from "./util.js";

const video = $("#video");
const timeListeners = new Set();
let loadedClipId = null;
let loadedVersion = null;
let raf = 0;
let stopAt = null;
let editedTime = 0;

export const onTime = (fn) => (timeListeners.add(fn), () => timeListeners.delete(fn));
export const isPlaying = () => !video.paused;
export const getTime = () => editedTime;
export const getLoadedClipId = () => loadedClipId;
export const getSourceTime = () => video.currentTime;

function emit() {
  const p = getProject();
  const e = loadedClipId && p ? tm.sourceToEdited(p.clips, loadedClipId, video.currentTime) : null;
  if (e !== null) editedTime = e;
  timeListeners.forEach((f) => f(editedTime));
}

async function loadClip(clipId, atSrc = 0) {
  const clip = getProject().clips.find((c) => c.id === clipId);
  if (!clip) return false;
  const version = clip.proxy_path ? 1 : 0;
  if (loadedClipId !== clipId || loadedVersion !== version) {
    loadedClipId = clipId;
    loadedVersion = version;
    video.src = `/media/${clipId}?p=${version}`;
    await new Promise((resolve) => {
      video.addEventListener("loadedmetadata", resolve, { once: true });
      video.addEventListener("error", () => {
        showError({ payload: { message: "เล่นวิดีโอนี้ในเบราว์เซอร์ไม่ได้",
          hint: "ถ้าเป็นไฟล์ HEVC/MKV ให้รอสร้างไฟล์พรีวิวให้เสร็จก่อน" } });
        resolve();
      }, { once: true });
    });
  }
  video.currentTime = atSrc;
  if (ui.currentClipId !== clipId) setCurrentClip(clipId);
  return true;
}

/** Jump the playhead to an edited-time position. */
export async function seek(t) {
  const p = getProject();
  const hit = p && tm.editedToSource(p.clips, t);
  if (!hit) return;
  editedTime = t;
  await loadClip(hit[0], hit[1]);
  emit();
}

/** Show a clip's first kept moment (or its start when everything is cut) for review. */
export async function showClip(clipId) {
  const p = getProject();
  const clip = p.clips.find((c) => c.id === clipId);
  if (!clip) return;
  const first = tm.enabledKeeps(clip)[0];
  await loadClip(clipId, first ? first.start : 0);
  emit();
}

function nextClipStart(p, clipId) {
  const i = p.clips.findIndex((c) => c.id === clipId);
  for (const c of p.clips.slice(i + 1)) {
    const k = tm.enabledKeeps(c)[0];
    if (k) return [c.id, k.start];
  }
  return null;
}

async function tick() {
  const p = getProject();
  if (video.paused || !p) return;
  const clip = p.clips.find((c) => c.id === loadedClipId);
  const keeps = clip ? tm.enabledKeeps(clip) : [];
  const t = video.currentTime;
  if (!keeps.some((k) => t >= k.start - 0.03 && t < k.end)) {
    const next = keeps.find((k) => k.start > t);
    if (next) video.currentTime = next.start;
    else {
      const nc = nextClipStart(p, loadedClipId);
      if (nc) await loadClip(nc[0], nc[1]), video.play();
      else {
        pause();
        editedTime = tm.editedDuration(p.clips);
      }
    }
  }
  emit();
  if (stopAt !== null && editedTime >= stopAt) {
    pause();
    return;
  }
  raf = requestAnimationFrame(tick);
}

export async function play(until = null) {
  const p = getProject();
  if (!p || !tm.segments(p.clips).length) return;
  stopAt = until;
  if (!loadedClipId) await seek(editedTime);
  if (editedTime >= tm.editedDuration(p.clips) - 0.05) await seek(0);
  await video.play().catch(() => {});
  cancelAnimationFrame(raf);
  raf = requestAnimationFrame(tick);
  timeListeners.forEach((f) => f(editedTime));
}

export function pause() {
  video.pause();
  cancelAnimationFrame(raf);
  stopAt = null;
  emit();
}

export const toggle = () => (isPlaying() ? pause() : play());

export async function playSelection() {
  const sel = getProject()?.selection;
  if (!sel) return;
  await seek(sel.start);
  await play(sel.end);
}

video.addEventListener("seeked", emit);
video.addEventListener("ended", () => !stopAt && pause());

// The loaded clip may have been removed, or its proxy may have just become available.
subscribe((why) => {
  const p = getProject();
  if (why !== "load" || !p) return;
  if (loadedClipId && !p.clips.some((c) => c.id === loadedClipId)) {
    pause();
    video.removeAttribute("src");
    video.load();
    loadedClipId = null;
    loadedVersion = null;
  }
  const c = p.clips.find((x) => x.id === loadedClipId);
  if (c && (c.proxy_path ? 1 : 0) !== loadedVersion) loadClip(c.id, video.currentTime);
});
