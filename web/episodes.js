// Split into episodes: the fewest files that each stay under a size limit; own intro per episode, shared outro.
import { api } from "./api.js";
import { getProject, withSavedProject } from "./state.js";
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

  const clipName = (id) => {
    const c = getProject().clips.find((x) => x.id === id);
    return c ? c.path.split(/[\\/]/).pop() : "";
  };

  async function plan() {
    out.replaceChildren();
    try {
      const r = await withSavedProject(() => api("POST", "/api/episodes/plan", { max_mb: +limit.value }));
      out.replaceChildren(
        el("table", { class: "ep-table" },
          el("tr", {}, ...["EP", "From – to", "Length", "Size up to", "Intro"].map((h) => el("th", {}, h))),
          ...r.episodes.map((e) => el("tr", {}, el("td", {}, String(e.index)), el("td", {}, `${fmtTime(e.start)} – ${fmtTime(e.end)}`),
            el("td", {}, fmtTime(e.duration)), el("td", {}, `${mb(e.est_bytes)} MB`), el("td", { class: "ep-intro" }, clipName(e.intro_clip_id) || "—")))),
        r.intro_reused ? el("p", { class: "muted small" }, `You have ${r.intro_clips} intro clip(s) for ${r.episodes.length} episodes, so the last one is reused.`) : "",
        !r.intro_clips ? el("p", { class: "muted small" }, "No intro clips: add them in Clips and set their role to Intro, one per episode, in order.") : "");
      return r;
    } catch (e) {
      showError(e);
      return null;
    }
  }

  planBtn.addEventListener("click", plan);
  exportBtn.addEventListener("click", async () => {
    const r = await plan();
    if (!r) return;
    if (!confirm(`Export ${r.episodes.length} episode(s), each under ${+limit.value} MB? This can take a while.`)) return;
    exportBtn.disabled = planBtn.disabled = true;
    try {
      const { job } = await withSavedProject(() => api("POST", "/api/episodes/export", { max_mb: +limit.value }));
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
    el("div", { class: "row" }, planBtn, exportBtn), out);
}
