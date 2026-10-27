import { getFonts, getProject, subscribe, update } from "./state.js";
import { $, el, numberSlider } from "./util.js";

export function initStylePanel() {
  const root = $("#style-panel");
  let built = false;
  const refs = {};

  const set = (key, value) => update((p) => (p.style[key] = value), "style");
  // percent=true: stored as 0..1, typed as 0..100
  const slider = (key, label, min, max, step, percent = false) => {
    const ns = numberSlider({ min, max, step, value: min, label, unit: percent ? "%" : "",
      toDisplay: percent ? (v) => v * 100 : (v) => v, fromDisplay: percent ? (d) => d / 100 : (d) => d,
      onInput: (v) => set(key, v) });
    refs[key] = { ns };
    return el("div", { class: "field" }, el("span", {}, label), ns.root);
  };
  const color = (key, label) => {
    const input = el("input", { type: "color" });
    input.addEventListener("input", () => set(key, input.value));
    refs[key] = { input };
    return el("label", { class: "field inline" }, el("span", {}, label), input);
  };

  const build = () => {
    const font = el("select", {}, getFonts().map((f) => el("option", { value: f }, f))); // the bundled fonts, from the server
    font.addEventListener("change", () => set("font", font.value));
    refs.font = { input: font };
    const bgOn = el("input", { type: "checkbox" });
    bgOn.addEventListener("change", () => set("bg_color", bgOn.checked ? refs.bg_color.input.value : null));
    refs.bgOn = { input: bgOn };
    const bg = el("input", { type: "color" });
    bg.addEventListener("input", () => bgOn.checked && set("bg_color", bg.value));
    refs.bg_color = { input: bg };
    const revealOn = el("input", { type: "checkbox", id: "opt-reveal" });
    revealOn.addEventListener("change", () => set("reveal", revealOn.checked));
    refs.revealOn = { input: revealOn };
    const reset = el("button", { class: "ghost", onclick: () => update((p) => p.subtitles.forEach((s) => (s.x = s.y = s.scale = null)), "subs-pos") },
      "Reset all subtitle positions");
    root.replaceChildren(
      el("h2", {}, "Subtitle style"),
      el("label", { class: "field" }, el("span", {}, "Font"), font),
      slider("size", "Size", 24, 160, 2),
      el("div", { class: "row" }, color("color", "Text color"), color("outline_color", "Outline color")),
      slider("outline_width", "Outline width", 0, 12, 1),
      slider("shadow", "Shadow", 0, 8, 1),
      el("label", { class: "field inline" }, el("span", {}, "Box background"), bgOn, bg),
      slider("default_x", "Horizontal position", 0, 1, 0.01, true),
      slider("default_y", "Vertical position", 0, 1, 0.01, true),
      el("label", { class: "field inline", title: "Each line fills in piece by piece over the time it is on screen" },
        el("span", {}, "Reveal text as it's spoken"), revealOn),
      el("p", { class: "muted small" }, "On the preview: drag a subtitle to move it, mouse wheel to resize it, double-click to edit its text. Type exact numbers in the boxes."),
      reset);
    built = true;
  };

  const sync = () => {
    const p = getProject();
    if (!p) return;
    if (!built) build();
    const st = p.style;
    for (const [k, r] of Object.entries(refs)) {
      if (k === "bgOn" || k === "bg_color" || k === "revealOn") continue;
      if (r.ns) { if (!r.ns.focused()) r.ns.sync(st[k]); continue; }
      if (document.activeElement !== r.input) r.input.value = st[k];
    }
    refs.revealOn.input.checked = !!st.reveal;
    refs.bgOn.input.checked = st.bg_color != null;
    refs.bg_color.input.value = st.bg_color ?? "#000000";
  };
  subscribe((why) => !why.startsWith("ov-") && why !== "subs-text" && why !== "subs-pos" && why !== "select" && sync());
}
