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

  // ---- file format, quality / target size, folder, and a size estimate ----
  const setExport = (patch) => update((p) => Object.assign(p.export, patch), "export");
  const option = (value, label) => el("option", { value }, label);
  const container = el("select", { id: "opt-container" },
    option("mp4", "MP4 (เปิดได้ทุกที่ แนะนำ)"), option("mov", "MOV"), option("mkv", "MKV"), option("webm", "WebM (เข้ารหัสช้ากว่า)"));
  const quality = el("select", { id: "opt-quality" },
    option("high", "คุณภาพสูง (ไฟล์ใหญ่)"), option("medium", "คุณภาพกลาง"), option("small", "ไฟล์เล็ก"), option("custom", "กำหนดขนาดเอง"));
  const target = el("input", { type: "number", id: "opt-target", min: 1, step: 1 });
  const targetRow = el("label", { class: "field" }, el("span", {}, "ขนาดไฟล์เป้าหมาย (MB)"), target);
  const folderText = el("span", { class: "folder-text small" });
  const estimate = el("p", { id: "estimate", class: "estimate small" });
  container.addEventListener("change", () => setExport({ container: container.value }));
  quality.addEventListener("change", () => setExport({ quality: quality.value, ...(quality.value === "custom" && !getProject().export.target_mb ? { target_mb: 20 } : {}) }));
  target.addEventListener("input", () => setExport({ target_mb: parseFloat(target.value) || null }));
  const setFolder = async (call) => {
    try {
      const r = await call();
      update((p) => (p.export.out_dir = r.out_dir), "export");
    } catch (e) {
      showError(e);
    }
  };
  const folderRow = el("div", { class: "field" }, el("span", {}, "บันทึกไฟล์ที่"), folderText,
    el("div", { class: "row" },
      el("button", { id: "opt-folder-pick", onclick: () => setFolder(() => api("POST", "/api/export-folder/pick")) }, "เลือกโฟลเดอร์…"),
      el("button", { class: "ghost", onclick: () => setFolder(() => api("POST", "/api/export-folder", { path: "" })) }, "ใช้โฟลเดอร์เริ่มต้น")));

  let lastSig = "", estimateSeq = 0, estimateTimer = null;
  const extrasSeconds = (p, role) => p.clips.filter((c) => c.role === role)
    .reduce((t, c) => t + tm.enabledKeeps(c).reduce((a, k) => a + k.end - k.start, 0), 0);
  const refreshEstimate = () => {
    const p = getProject();
    if (!p) return;
    const sig = JSON.stringify([p.selection, p.preset, p.export.container, p.export.quality, p.export.target_mb,
      p.clips.map((c) => [c.id, c.role, c.keeps])]);
    if (sig === lastSig) return;
    lastSig = sig;
    clearTimeout(estimateTimer);
    estimateTimer = setTimeout(async () => {
      const seq = ++estimateSeq;
      try {
        await flush(); // the server estimates from its saved copy
        const r = await api("POST", "/api/export/estimate");
        if (seq !== estimateSeq) return;
        const mb = r.bytes / 1048576;
        const parts = [extrasSeconds(p, "intro") && `ปกหัว ${fmtTime(extrasSeconds(p, "intro"))}`, `เนื้อหา ${fmtTime(p.selection ? p.selection.end - p.selection.start : tm.editedDuration(p.clips))}`,
          extrasSeconds(p, "outro") && `ปกท้าย ${fmtTime(extrasSeconds(p, "outro"))}`].filter(Boolean).join(" + ");
        estimate.textContent = `ความยาวไฟล์ ${fmtTime(r.seconds)} (${parts}) · ขนาดประมาณ ${mb >= 100 ? mb.toFixed(0) : mb.toFixed(1)} MB (±15%) · วิดีโอ ${(r.video_kbps / 1000).toFixed(1)} Mbps`;
      } catch (e) {
        if (seq === estimateSeq) estimate.textContent = e.payload?.code === "selection_invalid" ? "ยังประเมินขนาดไม่ได้: ช่วงที่เลือกไม่ถูกต้อง" : "";
      }
    }, 350);
  };

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
      const { video, srt, dir, downloadable } = done.result;
      const link = (name, label) => el("a", { href: `/exports/${encodeURIComponent(name)}`, download: name }, label);
      result.replaceChildren(el("strong", {}, "ส่งออกสำเร็จ"),
        downloadable ? el("div", { class: "row" }, link(video, `ดาวน์โหลด .${video.split(".").pop()}`), link(srt, "ดาวน์โหลด .srt")) : "",
        el("p", { class: "muted small" }, `ไฟล์ ${video} อยู่ที่โฟลเดอร์: ${dir}`));
    } catch (e) {
      showError(e);
    } finally {
      exportBtn.disabled = false;
    }
  });

  root.replaceChildren(el("h2", {}, "ส่งออก"), seg, framing,
    el("label", { class: "field" }, el("span", {}, "ชนิดไฟล์"), container),
    el("label", { class: "field" }, el("span", {}, "คุณภาพ / ขนาด"), quality), targetRow, folderRow, estimate,
    el("label", { class: "field inline" }, el("span", {}, "แสดงเส้นกันชนปุ่มของแอป"), safe),
    el("div", { class: "row" }, el("button", { onclick: checkFrame }, "ตรวจเฟรมจริง"), exportBtn), result);

  const render = () => {
    const p = getProject();
    const presets = getPresets();
    if (!p || !Object.keys(presets).length) return;
    container.value = p.export.container;
    quality.value = p.export.quality;
    targetRow.hidden = p.export.quality !== "custom";
    if (document.activeElement !== target) target.value = p.export.target_mb ?? "";
    folderText.textContent = p.export.out_dir || "โฟลเดอร์เริ่มต้นของโปรแกรม (VidcutProjects\\default\\exports)";
    refreshEstimate();
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
