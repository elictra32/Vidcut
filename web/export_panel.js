import { api, ApiError } from "./api.js";
import { flush, getPresets, getProject, setUi, subscribe, ui, update } from "./state.js";
import { trackJob } from "./status.js";
import { showError } from "./toast.js";
import * as tm from "./timeline_math.js";
import * as player from "./player.js";
import { $, el, fmtTime } from "./util.js";

const LABELS = { tiktok: "TikTok 9:16", youtube: "YouTube 16:9" };
const currentClip = () => {
  const p = getProject();
  return p?.clips.find((c) => c.id === (player.getLoadedClipId() ?? ui.currentClipId)) ?? null;
};

function setPreset(key) {
  update((p) => {
    p.preset = key;
    Object.assign(p.style, getPresets()[key].style_overrides); // each preset has its own subtitle size/position
  }, "preset");
}

async function checkFrame() {
  try {
    await flush();
    const res = await fetch("/api/preview-frame", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ t: player.getTime() }) });
    if (!res.ok) {
      const d = await res.json().catch(() => null);
      throw new ApiError(d?.error ?? { message: `HTTP ${res.status}` }, res.status);
    }
    const url = URL.createObjectURL(await res.blob());
    const dlg = el("dialog", { class: "frame-dialog" },
      el("p", { class: "muted small" }, "ภาพนี้สร้างจากกระบวนการส่งออกจริง (กรอบภาพ + ซับ ณ ตำแหน่งที่เล่นอยู่)"),
      el("img", { src: url, alt: "เฟรมตัวอย่างจากไฟล์ที่จะส่งออก" }),
      el("button", { class: "primary", onclick: () => dlg.close() }, "ปิด"));
    dlg.addEventListener("close", () => (URL.revokeObjectURL(url), dlg.remove()));
    document.body.append(dlg);
    dlg.showModal();
  } catch (e) {
    showError(e);
  }
}

export function initExportPanel() {
  const root = $("#export-panel");
  const result = el("div", { class: "export-result" });
  const framing = el("div", {});
  const seg = el("div", { class: "seg", role: "group", "aria-label": "เลือกแพลตฟอร์ม" });
  const safe = el("input", { type: "checkbox", checked: true });
  safe.addEventListener("change", () => setUi({ showSafeZone: safe.checked }, "safezone"));
  const exportBtn = el("button", { class: "primary" }, "ส่งออกวิดีโอ");

  exportBtn.addEventListener("click", async () => {
    const p = getProject();
    const total = tm.editedDuration(p.clips);
    if (!total) return showError({ payload: { message: "ยังไม่มีช่วงที่เก็บไว้ให้ส่งออก", hint: "เพิ่มคลิป หรือเปิดช่วงที่ถูกตัดกลับมา" } });
    if (!p.selection && !confirm(`ยังไม่ได้เลือกช่วง In/Out จะส่งออกทั้งไทม์ไลน์ (${fmtTime(total)}) ซึ่งอาจใช้เวลานาน ทำต่อไหม?`)) return;
    exportBtn.disabled = true;
    result.replaceChildren();
    try {
      await flush();
      const { job } = await api("POST", "/api/export", { preset: p.preset });
      const done = await trackJob("กำลังส่งออกวิดีโอ", job);
      if (!done) return;
      const { mp4, srt, dir } = done.result;
      const link = (name, label) => el("a", { href: `/exports/${encodeURIComponent(name)}`, download: name }, label);
      result.replaceChildren(el("strong", {}, "ส่งออกสำเร็จ"), el("div", { class: "row" }, link(mp4, "ดาวน์โหลด MP4"), link(srt, "ดาวน์โหลด .srt")),
        el("p", { class: "muted small" }, `ไฟล์อยู่ที่โฟลเดอร์: ${dir}`));
    } catch (e) {
      showError(e);
    } finally {
      exportBtn.disabled = false;
    }
  });

  root.replaceChildren(el("h2", {}, "ส่งออก"), seg, framing,
    el("label", { class: "field inline" }, el("span", {}, "แสดงเส้นกันชนปุ่มของแอป"), safe),
    el("div", { class: "row" }, el("button", { onclick: checkFrame }, "ตรวจเฟรมจริง"), exportBtn), result);

  const render = () => {
    const p = getProject();
    const presets = getPresets();
    if (!p || !Object.keys(presets).length) return;
    seg.replaceChildren(...Object.keys(presets).map((k) =>
      el("button", { "aria-pressed": String(p.preset === k), onclick: () => p.preset !== k && setPreset(k) }, LABELS[k] ?? k)));
    const clip = currentClip();
    const pr = presets[p.preset];
    framing.replaceChildren();
    if (!clip) return;
    if (Math.abs(clip.width / clip.height - pr.width / pr.height) < 0.01) {
      framing.append(el("p", { class: "muted small" }, "สัดส่วนของคลิปตรงกับ preset นี้ ไม่ต้องปรับกรอบภาพ"));
      return;
    }
    const setMode = (mode) => update(() => (clip.framing.mode = mode), "framing");
    const radio = (mode, label) => {
      const r = el("input", { type: "radio", name: "framing", checked: clip.framing.mode === mode });
      r.addEventListener("change", () => setMode(mode));
      return el("label", { class: "field inline" }, r, el("span", {}, label));
    };
    framing.append(el("h3", {}, "กรอบภาพของคลิปนี้"),
      radio("blur_fit", "เต็มภาพ + พื้นหลังเบลอ"), radio("crop", "ครอปเต็มจอ"));
    if (clip.framing.mode === "crop" && clip.width / clip.height > pr.width / pr.height) {
      const s = el("input", { type: "range", min: 0, max: 1, step: 0.01, value: clip.framing.crop_center_x });
      s.addEventListener("input", () => update(() => (clip.framing.crop_center_x = parseFloat(s.value)), "framing-x"));
      framing.append(el("label", { class: "field" }, el("span", {}, "ส่วนของภาพที่เก็บ (ซ้าย–ขวา)"), s),
        el("p", { class: "muted small" }, "หรือลากบนภาพตัวอย่างเพื่อเลื่อนกรอบ"));
    }
  };
  // "framing-x" fires while dragging the slider; re-rendering then would drop the slider mid-drag
  subscribe((why) => why !== "framing-x" && why !== "subs-text" && why !== "subs-pos" && why !== "subs" && why !== "select" && render());
}
