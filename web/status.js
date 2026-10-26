import { $, el } from "./util.js";
import { api, followJob, ApiError } from "./api.js";
import { showError } from "./toast.js";

/**
 * Show a job in the header status bar. Resolves with the finished job, or null when it
 * failed (error already toasted) or was cancelled.
 */
export async function trackJob(label, jobId) {
  const bar = $("#status");
  const text = el("span", {}, label);
  const prog = el("progress", { max: 1, value: 0 });
  const cancel = el("button", { class: "ghost", onclick: () => api("POST", `/api/jobs/${jobId}/cancel`) }, "ยกเลิก");
  bar.replaceChildren(text, prog, cancel);
  bar.hidden = false;
  try {
    const job = await followJob(jobId, (j) => {
      prog.value = j.percent;
      text.textContent = j.message ? `${label} · ${j.message}` : `${label} ${Math.round(j.percent * 100)}%`;
    });
    if (job.state === "error") {
      showError(new ApiError(job.error, 500));
      return null;
    }
    return job.state === "done" ? job : null;
  } finally {
    bar.hidden = true;
    bar.replaceChildren();
  }
}
