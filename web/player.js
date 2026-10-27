// Plays the project in EDITED time: playback skips over disabled keeps / dead-air gaps and hops to the
// next clip when one ends.
//
// Two <video> elements take turns. Seeking the visible one across a cut freezes the picture while the
// browser decodes up to the next keyframe (a second or more on long-GOP phone footage). So while one
// plays, the other (hidden) pre-seeks the next kept position; at the cut they swap.
import { getProject, subscribe, ui, setCurrentClip } from "./state.js";
import * as tm from "./timeline_math.js";
import { showError } from "./toast.js";

const LOOKAHEAD = 2.0; // seconds before a cut at which the hidden video starts preparing
const SWITCH_AT = 0.04; // swap when this close to the cut (about one frame)

const videos = [document.getElementById("video"), document.getElementById("video2")];
let video = videos[0]; // the visible one
let standby = videos[1]; // hidden, preparing the next position
let standbyPrep = null; // { key, clipId, src, ready }
const timeListeners = new Set();
let loadedClipId = null;
let loadedVersion = null;
let raf = 0;
let stopAt = null;
let editedTime = 0;
let review = false; // playing an intro/outro on its own (to look at a cover), not the edit
let wantPlay = false; // the user asked for playback; a <video> pauses by itself at the end of a file

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

/** Point `el` at a clip and a source time; resolves once it shows that frame. */
async function load(el, clipId, atSrc) {
  const clip = getProject().clips.find((c) => c.id === clipId);
  if (!clip) return false;
  const version = clip.proxy_path ? 1 : 0;
  if (el._clipId !== clipId || el._version !== version) {
    el._clipId = clipId;
    el._version = version;
    el.src = `/media/${clipId}?p=${version}`;
    await new Promise((resolve) => {
      el.addEventListener("loadedmetadata", resolve, { once: true });
      el.addEventListener("error", () => {
        if (el === video) {
          showError({ payload: { message: "This video can't be played in the browser",
            hint: "For HEVC/MKV files, wait for the preview file to finish building" } });
        }
        resolve();
      }, { once: true });
    });
  }
  if (Math.abs(el.currentTime - atSrc) > 0.01) {
    await new Promise((resolve) => {
      const done = () => (el.removeEventListener("seeked", done), clearTimeout(timer), resolve());
      const timer = setTimeout(done, 3000); // never wait forever on a stalled seek
      el.addEventListener("seeked", done);
      el.currentTime = atSrc;
    });
  }
  return true;
}

async function loadClip(clipId, atSrc = 0) {
  standbyPrep = null; // whatever was prepared no longer matches
  const ok = await load(video, clipId, atSrc);
  if (!ok) return false;
  loadedClipId = clipId;
  loadedVersion = video._version;
  if (ui.currentClipId !== clipId) setCurrentClip(clipId);
  return true;
}

/** Jump the playhead to an edited-time position. */
export async function seek(t) {
  review = false;
  const p = getProject();
  const hit = p && tm.editedToSource(p.clips, t);
  if (!hit) return;
  editedTime = t;
  await loadClip(hit[0], hit[1]);
  emit();
}

/** Show a clip's first kept moment (or its start when everything is cut) for review. */
export async function showClip(clipId) {
  review = false;
  const p = getProject();
  const clip = p.clips.find((c) => c.id === clipId);
  if (!clip) return;
  const first = tm.enabledKeeps(clip)[0];
  await loadClip(clipId, first ? first.start : 0);
  emit();
}

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

const prepKey = (target) => `${target.kind === "clip" ? target.clipId : loadedClipId}@${target.src}`;

/** Have the hidden video show the position playback is about to jump to. */
function prepare(target) {
  const key = prepKey(target);
  if (standbyPrep?.key === key) return;
  const clipId = target.kind === "clip" ? target.clipId : loadedClipId;
  const mine = (standbyPrep = { key, clipId, src: target.src, ready: false });
  standby.pause();
  load(standby, clipId, target.src).then((ok) => {
    if (ok && standbyPrep === mine) mine.ready = true;
  });
}

/** Make the prepared video the visible, playing one. False when it isn't ready (caller falls back to seeking). */
function swapIfReady(target) {
  if (!standbyPrep?.ready || standbyPrep.key !== prepKey(target)) return false;
  const next = standby;
  const prev = video;
  next.play().catch(() => {});
  next.classList.remove("standby");
  prev.classList.add("standby");
  prev.pause();
  video = next;
  standby = prev;
  standbyPrep = null;
  const changed = loadedClipId !== video._clipId;
  loadedClipId = video._clipId;
  loadedVersion = video._version;
  if (changed && ui.currentClipId !== loadedClipId) setCurrentClip(loadedClipId);
  return true;
}

async function tick() {
  const p = getProject();
  if (!wantPlay || !p) return;
  if (review) { // a cover on its own: play it to its end, then stop
    const c = p.clips.find((x) => x.id === loadedClipId);
    const last = c && tm.enabledKeeps(c).at(-1);
    if (video.ended || !last || video.currentTime >= last.end - 0.03) return pause();
    emit();
    raf = requestAnimationFrame(tick);
    return;
  }
  let swapped = false;
  const b = tm.upcomingBoundary(p.clips, loadedClipId, video.currentTime);
  if (b && (b.target.kind === "seek" || b.target.kind === "clip")) {
    const remaining = b.at - video.currentTime;
    if (remaining <= LOOKAHEAD) prepare(b.target);
    if (remaining <= SWITCH_AT) swapped = swapIfReady(b.target);
  }
  if (!swapped && !(await advance())) return;
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
  if (loaded && (loaded.role ?? "main") !== "main") {
    // an intro/outro the user opened: play just that clip (from its start if it is at the end)
    const keeps = tm.enabledKeeps(loaded);
    if (!keeps.length) return;
    review = true;
    if (video.currentTime >= keeps.at(-1).end - 0.05) video.currentTime = keeps[0].start;
    wantPlay = true;
    await video.play().catch(() => {});
    cancelAnimationFrame(raf);
    raf = requestAnimationFrame(tick);
    return;
  }
  if (!loaded) await seek(editedTime);
  if (editedTime >= tm.editedDuration(p.clips) - 0.05) await seek(0);
  wantPlay = true;
  await video.play().catch(() => {});
  cancelAnimationFrame(raf);
  raf = requestAnimationFrame(tick);
  timeListeners.forEach((f) => f(editedTime));
}

export function pause() {
  wantPlay = false;
  review = false;
  for (const v of videos) v.pause();
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

for (const v of videos) {
  v.addEventListener("seeked", () => v === video && emit());
  // A file that ends exactly at its last kept moment never produces a frame outside a keep, so the
  // playback loop alone can't see it: 'ended' pauses the <video>, and we must move on to the next clip.
  v.addEventListener("ended", async () => {
    if (v !== video || !wantPlay) return;
    if (review) return pause();
    if (await advance()) {
      cancelAnimationFrame(raf);
      raf = requestAnimationFrame(tick);
    }
  });
}

// A loaded clip may have been removed, or its proxy may have just become available.
subscribe((why) => {
  const p = getProject();
  if (why !== "load" || !p) return;
  standbyPrep = null;
  for (const v of videos) {
    if (v._clipId && !p.clips.some((c) => c.id === v._clipId)) {
      if (v === video) pause();
      v.removeAttribute("src");
      v.load();
      v._clipId = v._version = null;
    }
  }
  if (loadedClipId && !p.clips.some((c) => c.id === loadedClipId)) {
    loadedClipId = null;
    loadedVersion = null;
  }
  const c = p.clips.find((x) => x.id === loadedClipId);
  if (c && (c.proxy_path ? 1 : 0) !== loadedVersion) loadClip(c.id, video.currentTime);
});
