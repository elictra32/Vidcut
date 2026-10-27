import { $, el } from "./util.js";
import { api, followJob, ApiError } from "./api.js";
import { showError } from "./toast.js";

// The header status area holds ONE ROW PER RUNNING JOB (an export, covers being made, dead-air detection...), so starting
// something else never hides or replaces a job that is still going. The queue shows its running item as one more row.
const rows = new Map(); // key -> row element

function put(key, row) {
  const bar = $("#status");
  const old = rows.get(key);
  if (old) old.replaceWith(row); else bar.append(row);
  rows.set(key, row);
  bar.hidden = false;
}

function drop(key) {
  rows.get(key)?.remove();
  rows.delete(key);
  if (!rows.size) $("#status").hidden = true;
}

/**
 * Show a job in the header status area. Resolves with the finished job, or null when it
 * failed (error already toasted) or was cancelled.
 */
export async function trackJob(label, jobId) {
  const key = `job:${jobId}`;
  const text = el("span", {}, label);
  const prog = el("progress", { max: 1, value: 0 });
  const cancel = el("button", { class: "ghost", onclick: () => api("POST", `/api/jobs/${jobId}/cancel`) }, "Cancel");
  put(key, el("div", { class: "status-job", "data-kind": "job" }, text, prog, cancel));
  try {
    const job = await followJob(jobId, (j) => {
      prog.value = j.percent;
      text.textContent = j.state === "queued" ? `${label} · waiting for the previous job`
        : j.message ? `${label} · ${j.message}` : `${label} ${Math.round(j.percent * 100)}%`;
    });
    if (job.state === "error") {
      showError(new ApiError(job.error, 500));
      return null;
    }
    return job.state === "done" ? job : null;
  } finally {
    drop(key);
  }
}

/** The queue's state as one row: { text, percent } while something runs or waits, null when the queue is idle. */
export function setQueueRow(info) {
  if (!info) return drop("queue");
  const text = el("span", {}, info.text);
  const kids = [text];
  if (info.percent != null) kids.push(el("progress", { max: 1, value: info.percent }));
  put("queue", el("div", { class: "status-job", "data-kind": "queue", title: "Click to open the queue", onclick: () => $("#queue-panel").scrollIntoView({ behavior: "smooth", block: "start" }) }, ...kids));
}
