import { api } from "./api.js";
import { getProject, reloadAfterJob, ui } from "./state.js";
import { trackJob } from "./status.js";
import { showError, showToast } from "./toast.js";
import { $, el } from "./util.js";

const FIELDS = [
  ["noise_db", "Level counted as silence (dB)", -35, -60, -10, 1, "Lower values (e.g. -50) cut only truly silent parts"],
  ["min_silence", "Silence longer than (seconds)", 0.6, 0.2, 3, 0.1, "Shorter silences are kept"],
  ["padding", "Padding around speech (seconds)", 0.15, 0, 0.5, 0.05, "Keeps a little silence around speech so it isn't cut abruptly"],
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
    if (!clip) return showToast("Select a clip first", "error");
    const before = structuredClone(getProject().clips);
    try {
      const body = Object.fromEntries(Object.entries(inputs).map(([k, i]) => [k, parseFloat(i.value)]));
      const { job } = await api("POST", `/api/clips/${clip.id}/silence`, body);
      const done = await trackJob("Finding dead air", job);
      if (!done) return;
      await reloadAfterJob(before);
      const n = done.result.keeps.length;
      showToast(`Found ${n} sections to keep · dead air removed`);
    } catch (e) {
      showError(e);
    }
  } }, "Detect and cut dead air");
  root.replaceChildren(el("h2", {}, "Cut dead air"), ...rows, run,
    el("p", { class: "muted small" }, "Applies to the selected clip only. Review or adjust each section in the “Review cuts” bar below"));
}
