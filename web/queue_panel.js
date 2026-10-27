// The job queue: exports and episode batches that run one after another, kept even when the app is closed.
import { api } from "./api.js";
import { flush, getProject } from "./state.js";
import { showError, showToast } from "./toast.js";
import { setQueueRow } from "./status.js";
import { $, el } from "./util.js";

const STATE_LABEL = { queued: "Waiting", running: "Running", done: "Done", error: "Failed", cancelled: "Cancelled" };

let refresh = () => {};

/** Put the current project (as it is right now) in the queue. `kind` is "export" or "episodes". */
export async function addToQueue(kind, params = {}) {
  try {
    if (!(await flush())) return null; // the server must hold the latest edits: the queue freezes a copy of them
    const item = await api("POST", "/api/queue", { kind, params: { preset: getProject().preset, ...params } });
    showToast("Added to the queue. Its progress shows at the top of the page, and you can keep working.", "info", 5000);
    refresh();
    return item;
  } catch (e) {
    showError(e);
    return null;
  }
}

const sizeText = (b) => `${(b / 1048576) >= 100 ? (b / 1048576).toFixed(0) : (b / 1048576).toFixed(1)} MB`;

function resultText(it) {
  const r = it.result;
  if (!r) return "";
  if (r.files) return `${r.files.length} ${r.kind === "highlights" ? "highlight" : "episode"} file(s) in ${r.dir}${r.files.some((f) => f.over_limit) ? " · some are over the size limit" : ""}`;
  return `${r.video} in ${r.dir}`;
}

export function initQueuePanel() {
  const root = $("#queue-panel");
  const list = el("div", { class: "q-list" });
  const pause = el("button", { id: "btn-queue-pause", onclick: async () => {
    try { await api("POST", `/api/queue/${pause.dataset.paused === "1" ? "resume" : "pause"}`); refresh(); } catch (e) { showError(e); }
  } }, "Pause queue");
  const clear = el("button", { class: "ghost", id: "btn-queue-clear", onclick: async () => {
    try { await api("POST", "/api/queue/clear-finished"); refresh(); } catch (e) { showError(e); }
  } }, "Clear finished");
  const badge = $("#queue-badge");
  root.replaceChildren(el("h2", {}, "Queue"),
    el("p", { class: "muted small" }, "Exports wait here and run one after another. Each keeps the project as it was when you added it. Closing Vidcut is fine: unfinished items continue the next time you open it."),
    el("div", { class: "row" }, pause, clear), list);

  const act = (method, path, body) => async () => {
    try { await api(method, path, body); refresh(); } catch (e) { showError(e); }
  };

  const seen = new Map(); // item id -> last state, to announce when something finishes
  const announce = (q) => {
    for (const it of q.items) {
      const before = seen.get(it.id);
      seen.set(it.id, it.state);
      if (before === undefined || before === it.state) continue;   // first look at the list, or nothing new
      if (it.state === "done") showToast(`Finished: ${it.label} — ${resultText(it)}`, "info", 9000);
      else if (it.state === "error") showToast(`Failed: ${it.label} — ${it.error?.message ?? ""}`, "error", 9000);
    }
  };
  // the header shows what the queue is doing, so it never looks idle while it works
  const headerRow = (q) => {
    const running = q.items.find((i) => i.state === "running");
    const waiting = q.items.filter((i) => i.state === "queued").length;
    if (running) {
      const label = running.label.length > 48 ? `${running.label.slice(0, 47)}…` : running.label;
      setQueueRow({ text: `Queue: ${label} ${Math.round(running.percent * 100)}%${running.message ? ` · ${running.message}` : ""}${waiting ? ` · ${waiting} waiting` : ""}`, percent: running.percent });
    } else if (waiting) {
      setQueueRow({ text: q.paused ? `Queue paused · ${waiting} waiting` : q.blocked ? `Queue: ${waiting} waiting for the other job to finish` : `Queue: ${waiting} waiting` });
    } else setQueueRow(null);
  };

  const render = (q) => {
    announce(q);
    headerRow(q);
    pause.textContent = q.paused ? "Resume queue" : "Pause queue";
    pause.dataset.paused = q.paused ? "1" : "0";
    const waiting = q.items.filter((i) => i.state === "queued" || i.state === "running").length;
    if (badge) { badge.textContent = waiting ? String(waiting) : ""; badge.hidden = !waiting; }
    list.replaceChildren(...(q.items.length ? q.items.map((it, idx) => {
      const queuedIdx = q.items.filter((i) => i.state === "queued").indexOf(it);
      const nQueued = q.items.filter((i) => i.state === "queued").length;
      return el("div", { class: `q-item q-${it.state}`, "data-id": it.id },
        el("div", { class: "row" }, el("strong", { class: "q-label", title: it.label }, it.label), el("span", { class: "spacer" }),
          it.state === "queued" ? el("button", { class: "ghost icon", title: "Move up", disabled: queuedIdx <= 0, onclick: act("POST", `/api/queue/${it.id}/move`, { delta: -1 }) }, "↑") : "",
          it.state === "queued" ? el("button", { class: "ghost icon", title: "Move down", disabled: queuedIdx >= nQueued - 1, onclick: act("POST", `/api/queue/${it.id}/move`, { delta: 1 }) }, "↓") : "",
          it.state === "queued" || it.state === "running"
            ? el("button", { class: "ghost icon q-cancel", title: it.state === "running" ? "Stop this job" : "Cancel", onclick: act("POST", `/api/queue/${it.id}/cancel`) }, "✕")
            : el("button", { class: "ghost icon q-remove", title: "Remove from the list", onclick: act("DELETE", `/api/queue/${it.id}`) }, "✕")),
        el("div", { class: "muted small" }, `${STATE_LABEL[it.state] ?? it.state}${it.state === "queued" && q.blocked ? " · waiting for the other job to finish" : ""}${it.state === "running" ? ` · ${Math.round(it.percent * 100)}%` : ""}${it.message ? ` · ${it.message}` : ""}`),
        it.state === "running" ? el("progress", { max: 1, value: it.percent }) : "",
        it.state === "done" ? el("div", { class: "muted small" }, resultText(it)) : "",
        it.state === "error" ? el("div", { class: "q-error small" }, it.error?.message ?? "Failed", it.error?.hint ? ` — ${it.error.hint}` : "") : "");
    }) : [el("p", { class: "muted small" }, "Nothing in the queue. Use “Add to queue” next to an export button.")]));
  };

  let timer = 0;
  refresh = async () => {
    clearTimeout(timer);
    let next = 5000;
    try {
      const q = await api("GET", "/api/queue");
      render(q);
      if (q.items.some((i) => i.state === "running" || i.state === "queued")) next = 1500;
    } catch { /* the server is away for a moment: try again */ }
    timer = setTimeout(refresh, next);
  };
  refresh();
}
