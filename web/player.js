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
export const isPlaying = () => wantPlay;
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

let wantPlay = false; // the user asked for playback; <video> flips to paused by itself at the end of a file

/** Apply tm.nextPlayTarget: skip gaps, hop clips, or stop. Returns false when playback ended. */
async function advance() {
  const p = getProject();
  const target = tm.nextPlayTarget(p.clips, loadedClipId, video.currentTime);
  if (target.kind === "seek") video.currentTime = target.src;
  else if (target.kind === "clip") {
    await loadClip(target.clipId, target.src);
    await video.play().catch(() => {});
  } else if (target.kind === "end") {
    pause();
    editedTime = tm.editedDuration(p.clips);
    return false;
  }
  return true;
}

async function tick() {
  const p = getProject();
  if (!wantPlay || !p) return;
  if (!(await advance())) return;
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
  const loaded = p.clips.find((c) => c.id === loadedClipId);
  if (!loaded || (loaded.role ?? "main") !== "main") await seek(editedTime); // an intro/outro is only for review: play the main timeline
  if (editedTime >= tm.editedDuration(p.clips) - 0.05) await seek(0);
  wantPlay = true;
  await video.play().catch(() => {});
  cancelAnimationFrame(raf);
  raf = requestAnimationFrame(tick);
  timeListeners.forEach((f) => f(editedTime));
}

export function pause() {
  wantPlay = false;
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
// A file that ends exactly at its last kept moment never produces a frame outside a keep, so the
// playback loop alone can't see it: 'ended' pauses the <video>, and we must move on to the next clip.
video.addEventListener("ended", async () => {
  if (!wantPlay) return;
  if (await advance()) {
    cancelAnimationFrame(raf);
    raf = requestAnimationFrame(tick);
  }
});

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
