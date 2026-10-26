import { api } from "./api.js";
import { getProject, loadProject, reloadAfterJob, setCurrentClip, subscribe, ui, update, updateKeeps } from "./state.js";
import { remapSelection } from "./timeline_math.js";
import { trackJob } from "./status.js";
import { showError, showToast } from "./toast.js";
import * as player from "./player.js";
import { $, basename, el, fmtTime } from "./util.js";

async function afterAdd(res) {
  if (!res.clip) return; // file dialog cancelled
  await loadProject();
  setCurrentClip(res.clip.id);
  if (res.job) {
    // non-browser-playable source: wait for the preview copy before showing it
    await trackJob("กำลังสร้างไฟล์พรีวิว", res.job);
    await reloadAfterJob();
  }
  await player.showClip(res.clip.id);
}

export async function addClipFromDialog() {
  try {
    await afterAdd(await api("POST", "/api/clips/pick"));
  } catch (e) {
    showError(e);
  }
}

export async function addClipFromPath(path) {
  if (!path.trim()) return;
  try {
    await afterAdd(await api("POST", "/api/clips", { path: path.trim().replace(/^"|"$/g, "") }));
  } catch (e) {
    showError(e);
  }
}

const ROLE_LABELS = { main: "คลิปหลัก", intro: "ปกหัว", outro: "ปกท้าย" };

/** Intro/outro clips leave the edit timeline (so the In/Out selection stays on the main clip). */
function setRole(id, role) {
  updateKeeps((p) => (p.clips.find((c) => c.id === id).role = role));
}

function removeClip(id) {
  const before = structuredClone(getProject().clips);
  update((p) => {
    p.clips = p.clips.filter((c) => c.id !== id);
    p.subtitles = p.subtitles.filter((s) => s.clip_id !== id);
    p.selection = remapSelection(before, p.clips, p.selection);
  }, "load");
  if (ui.currentClipId === id) setCurrentClip(getProject().clips[0]?.id ?? null);
}

async function clearTemp() {
  try {
    const { freed_bytes } = await api("POST", "/api/clear-temp");
    showToast(`ล้างไฟล์ชั่วคราวแล้ว (คืนพื้นที่ ${(freed_bytes / 1048576).toFixed(1)} MB)`);
  } catch (e) {
    showError(e);
  }
}

export function initClipsPanel() {
  const root = $("#clips-panel");
  const render = () => {
    const p = getProject();
    const list = el("ul", { class: "clip-list" });
    for (const c of p?.clips ?? []) {
      list.append(el("li", { class: c.id === ui.currentClipId ? "active" : "" },
        el("button", { class: "clip-main", onclick: () => (setCurrentClip(c.id), player.showClip(c.id)) },
          el("span", { class: "clip-name", title: c.path }, basename(c.path)),
          el("span", { class: "muted" }, `${fmtTime(c.duration)} · ${c.width}×${c.height}${c.has_audio ? "" : " · ไม่มีเสียง"}`)),
        el("select", { class: "role", "aria-label": "บทบาทของคลิป", title: "ปกหัว/ปกท้ายจะถูกต่อหน้า/หลังช่วงที่เลือกตอนส่งออก",
          onchange: (e) => setRole(c.id, e.target.value) },
          Object.entries(ROLE_LABELS).map(([v, label]) => el("option", { value: v, selected: (c.role ?? "main") === v }, label))),
        el("button", { class: "ghost icon", title: "เอาคลิปออกจากโปรเจกต์ (ไม่ลบไฟล์)", onclick: () => removeClip(c.id) }, "✕")));
    }
    root.replaceChildren(el("h2", {}, "คลิป"),
      p?.clips.length ? list : el("p", { class: "muted" }, "ยังไม่มีคลิป กด “เพิ่มคลิป” ด้านบน"),
      el("button", { class: "ghost small", title: "ลบไฟล์พรีวิวที่ไม่ได้ใช้และโฟลเดอร์ชั่วคราว (ไม่แตะไฟล์ต้นฉบับ)", onclick: clearTemp }, "ล้างไฟล์ชั่วคราว"));
  };
  subscribe(render);
  render();
}
