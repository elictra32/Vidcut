import { getProject, subscribe, update } from "./state.js";
import { $, el } from "./util.js";

// Fonts shipped in /fonts: the browser preview and the ffmpeg export both use these.
const FONTS = ["Sarabun", "Prompt"];

export function initStylePanel() {
  const root = $("#style-panel");
  let built = false;
  const refs = {};

  const set = (key, value) => update((p) => (p.style[key] = value), "style");
  const slider = (key, label, min, max, step, fmt = (v) => v) => {
    const out = el("output", {});
    const input = el("input", { type: "range", min, max, step });
    input.addEventListener("input", () => (set(key, parseFloat(input.value)), (out.textContent = fmt(parseFloat(input.value)))));
    refs[key] = { input, out, fmt };
    return el("label", { class: "field" }, el("span", {}, label, " ", out), input);
  };
  const color = (key, label) => {
    const input = el("input", { type: "color" });
    input.addEventListener("input", () => set(key, input.value));
    refs[key] = { input };
    return el("label", { class: "field inline" }, el("span", {}, label), input);
  };

  const build = () => {
    const font = el("select", {}, FONTS.map((f) => el("option", { value: f }, f)));
    font.addEventListener("change", () => set("font", font.value));
    refs.font = { input: font };
    const bgOn = el("input", { type: "checkbox" });
    bgOn.addEventListener("change", () => set("bg_color", bgOn.checked ? refs.bg_color.input.value : null));
    refs.bgOn = { input: bgOn };
    const bg = el("input", { type: "color" });
    bg.addEventListener("input", () => bgOn.checked && set("bg_color", bg.value));
    refs.bg_color = { input: bg };
    const reset = el("button", { class: "ghost", onclick: () => update((p) => p.subtitles.forEach((s) => (s.x = s.y = null)), "subs-pos") },
      "รีเซ็ตตำแหน่งซับทุกบรรทัด");
    root.replaceChildren(
      el("h2", {}, "สไตล์ซับ"),
      el("label", { class: "field" }, el("span", {}, "ฟอนต์"), font),
      slider("size", "ขนาด", 24, 160, 2),
      el("div", { class: "row" }, color("color", "สีตัวอักษร"), color("outline_color", "สีขอบ")),
      slider("outline_width", "ความหนาขอบ", 0, 12, 1),
      slider("shadow", "เงา", 0, 8, 1),
      el("label", { class: "field inline" }, el("span", {}, "พื้นหลังกล่อง"), bgOn, bg),
      slider("default_x", "ตำแหน่งแนวนอน", 0, 1, 0.01, (v) => `${Math.round(v * 100)}%`),
      slider("default_y", "ตำแหน่งแนวตั้ง", 0, 1, 0.01, (v) => `${Math.round(v * 100)}%`),
      el("p", { class: "muted small" }, "ลากซับบนภาพตัวอย่างเพื่อย้ายเฉพาะบรรทัดนั้น (ดับเบิลคลิกเพื่อคืนตำแหน่งเริ่มต้น)"),
      reset);
    built = true;
  };

  const sync = () => {
    const p = getProject();
    if (!p) return;
    if (!built) build();
    const st = p.style;
    for (const [k, r] of Object.entries(refs)) {
      if (k === "bgOn" || k === "bg_color") continue;
      if (document.activeElement !== r.input) r.input.value = st[k];
      if (r.out) r.out.textContent = r.fmt(st[k]);
    }
    refs.bgOn.input.checked = st.bg_color != null;
    refs.bg_color.input.value = st.bg_color ?? "#000000";
  };
  subscribe((why) => why !== "subs-text" && why !== "subs-pos" && why !== "select" && sync());
}
