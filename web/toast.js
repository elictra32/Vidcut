import { el, $ } from "./util.js";

export function showToast(message, kind = "info", ms = 4000) {
  const t = el("div", { class: `toast ${kind}` }, message);
  $("#toasts").append(t);
  setTimeout(() => t.remove(), ms);
}

/** Thai message + suggested fix, with technical details folded away. */
export function showError(err) {
  const p = err.payload ?? { message: err.message || String(err) };
  const box = el("div", { class: "toast error" },
    el("strong", {}, p.message),
    p.hint ? el("div", { class: "hint" }, p.hint) : "",
    p.details ? el("details", {}, el("summary", {}, "รายละเอียด"),
      el("pre", {}, typeof p.details === "string" ? p.details : JSON.stringify(p.details, null, 2))) : "",
    el("button", { class: "toast-close", onclick: () => box.remove(), "aria-label": "ปิด" }, "×"));
  $("#toasts").append(box);
}
