// Split into episodes: the fewest files that each stay under a size limit; own intro per episode, shared outro.
import { api } from "./api.js";
import { getProject, withSavedProject } from "./state.js";
import { addToQueue } from "./queue_panel.js";
import { trackJob } from "./status.js";
import { showError } from "./toast.js";
import { $, el, fmtTime, recall, remember } from "./util.js";

const mb = (bytes) => (bytes / 1048576 >= 100 ? (bytes / 1048576).toFixed(0) : (bytes / 1048576).toFixed(1));

export function initEpisodes() {
  const root = $("#episodes-panel");
  const limit = el("input", { type: "number", id: "ep-limit", min: 5, step: 10, value: recall("vidcut.epLimit", 500) });
  limit.addEventListener("change", () => remember("vidcut.epLimit", +limit.value));
  const out = el("div", { class: "ep-out" });
  const planBtn = el("button", { id: "btn-plan-eps" }, "Plan episodes");
  const exportBtn = el("button", { id: "btn-export-eps", class: "primary" }, "Export all episodes");

  let picks = []; // the intro chosen for each episode (clip ids)
  let planned = null; // { limit, r } of the plan on screen

  async function plan() {
    out.replaceChildren();
    try {
      planBtn.textContent = "Measuring…"; // the plan encodes a few short samples to learn the real size of this footage
      const r = await withSavedProject(() => api("POST", "/api/episodes/plan", { max_mb: +limit.value }));
      out.replaceChildren(
        el("table", { class: "ep-table" },
          el("tr", {}, ...["EP", "From – to", "Length", "Size", "Intro"].map((h) => el("th", {}, h))),
          ...r.episodes.map((e, i) => {
            const sel = el("select", { class: "ep-intro-pick", "aria-label": `Intro for episode ${e.index}` },
              el("option", { value: "" }, "(none)"), ...r.intros.map((c) => el("option", { value: c.id, title: c.name }, c.name)));
            sel.value = e.intro_clip_id ?? "";
            sel.addEventListener("change", () => (picks[i] = sel.value));
            return el("tr", {}, el("td", {}, String(e.index)), el("td", {}, `${fmtTime(e.start)} – ${fmtTime(e.end)}`),
              el("td", {}, fmtTime(e.duration)), el("td", { title: `About ${mb(e.est_bytes)} MB; the encoder never goes above ${mb(e.max_bytes || e.est_bytes)} MB` }, `≈ ${mb(e.est_bytes)} MB`), el("td", { class: "ep-intro" }, sel));
          })),
        r.intro_reused ? el("p", { class: "muted small" }, `You have ${r.intro_clips} intro clip(s) for ${r.episodes.length} episodes, so the last one is reused.`) : "",
        !r.intro_clips ? el("p", { class: "muted small" }, "No intro clips: add them in Clips and set their role to Intro, one per episode, in order.") : "");
      picks = r.episodes.map((e) => e.intro_clip_id ?? "");
      planned = { limit: +limit.value, r };
      return r;
    } catch (e) {
      showError(e);
      return null;
    } finally {
      planBtn.textContent = "Plan episodes";
    }
  }

  planBtn.addEventListener("click", plan);
  exportBtn.addEventListener("click", async () => {
    // keep the intro choices made in the table: only plan again when there is no plan for this limit
    const r = planned && planned.limit === +limit.value ? planned.r : await plan();
    if (!r) return;
    if (!confirm(`Export ${r.episodes.length} episode(s), each under ${+limit.value} MB? This can take a while.`)) return;
    exportBtn.disabled = planBtn.disabled = true;
    try {
      const { job } = await withSavedProject(() => api("POST", "/api/episodes/export", { max_mb: +limit.value, ...(picks.length ? { intro_ids: picks } : {}), ...(planned?.r.measured_kbps ? { measured_kbps: planned.r.measured_kbps } : {}) }));
      const done = await trackJob("Exporting episodes", job);
      if (!done) return;
      const { files, dir, limit_mb } = done.result;
      out.replaceChildren(el("strong", {}, `${files.length} episode(s) exported`),
        ...files.map((f) => el("div", { class: `ep-file${f.over_limit ? " over" : ""}` }, `${f.video} · ${mb(f.bytes)} MB${f.over_limit ? ` — over the ${limit_mb} MB limit` : ""}`)),
        el("p", { class: "muted small" }, `Files are in folder: ${dir}`));
    } catch (e) {
      showError(e);
    } finally {
      exportBtn.disabled = planBtn.disabled = false;
    }
  });

  root.replaceChildren(
    el("h2", {}, "Split into episodes"),
    el("p", { class: "muted small" }, "Cuts the timeline (or your In/Out range) into the fewest files that each fit the size limit, at dead-air cuts. Each episode gets its own intro clip (in order); the outro is the same for all."),
    el("label", { class: "field" }, el("span", {}, "Max size per episode (MB)"), limit),
    el("div", { class: "row" }, planBtn, exportBtn,
      el("button", { id: "btn-queue-eps", title: "Add all episodes to the queue instead of running them now", onclick: async () => {
        const r = planned && planned.limit === +limit.value ? planned.r : await plan();
        if (r) addToQueue("episodes", { max_mb: +limit.value, ...(picks.length ? { intro_ids: picks } : {}), ...(planned?.r.measured_kbps ? { measured_kbps: planned.r.measured_kbps } : {}) });
      } }, "Add to queue")), out);
}
