import { api } from "./api.js";
import { getProject, reloadAfterJob, ui } from "./state.js";
import { trackJob } from "./status.js";
import { showError, showToast } from "./toast.js";
import { $, el } from "./util.js";

const FIELDS = [
  ["noise_db", "ความดังที่ถือว่าเงียบ (dB)", -35, -60, -10, 1, "ยิ่งค่าน้อย (เช่น -50) ยิ่งตัดเฉพาะที่เงียบจริง ๆ"],
  ["min_silence", "เงียบนานกว่า (วินาที)", 0.6, 0.2, 3, 0.1, "ช่วงเงียบที่สั้นกว่านี้จะไม่ถูกตัด"],
  ["padding", "เผื่อหัวท้ายคำพูด (วินาที)", 0.15, 0, 0.5, 0.05, "เก็บช่วงเงียบสั้น ๆ รอบคำพูดไว้ ไม่ให้ตัดห้วน"],
];

export function initSilencePanel() {
  const root = $("#silence-panel");
  const inputs = {};
  const rows = FIELDS.map(([key, label, val, min, max, step, tip]) => {
    inputs[key] = el("input", { type: "number", value: val, min, max, step, title: tip });
    return el("label", { class: "field" }, el("span", {}, label), inputs[key]);
  });
  const run = el("button", { class: "primary", onclick: async () => {
    const clip = getProject()?.clips.find((c) => c.id === ui.currentClipId);
    if (!clip) return showToast("เลือกคลิปก่อน", "error");
    const before = structuredClone(getProject().clips);
    try {
      const body = Object.fromEntries(Object.entries(inputs).map(([k, i]) => [k, parseFloat(i.value)]));
      const { job } = await api("POST", `/api/clips/${clip.id}/silence`, body);
      const done = await trackJob("กำลังหา Dead air", job);
      if (!done) return;
      await reloadAfterJob(before);
      const n = done.result.keeps.length;
      showToast(`พบ ${n} ช่วงที่เก็บไว้ · ตัด Dead air ออกแล้ว`);
    } catch (e) {
      showError(e);
    }
  } }, "ตรวจหาและตัด Dead air");
  root.replaceChildren(el("h2", {}, "ตัด Dead air"), ...rows, run,
    el("p", { class: "muted small" }, "ตัดเฉพาะคลิปที่เลือกอยู่ แล้วตรวจ/แก้ทีละช่วงได้ที่แถบ “ตรวจช่วงที่ตัด” ด้านล่าง"));
}
