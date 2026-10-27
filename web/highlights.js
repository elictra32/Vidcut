// Find highlight moments for short clips: a free local scan (word lists + loudness), and a hand-off to an AI
// (copy the transcript with a ready prompt, paste its answer back).
import { api } from "./api.js";
import { getProject, update, withSavedProject } from "./state.js";
import * as player from "./player.js";
import { parseRanges } from "./ranges.js";
import * as tm from "./timeline_math.js";
import { showError, showToast } from "./toast.js";
import { $, el, fmtTime, recall, remember } from "./util.js";

const LABELS = { scold: "Scolding", wisdom: "Wake-up call", funny: "Funny", general: "Energetic", other: "AI pick" };
const ORDER = ["scold", "wisdom", "funny", "general", "other"];

function useRange(c) {
  update((p) => (p.selection = { start: +c.start.toFixed(3), end: +c.end.toFixed(3) }), "selection");
  showToast(`Selection set to ${fmtTime(c.start)} – ${fmtTime(c.end)}`);
}

async function preview(c) {
  await player.seek(c.start);
  await player.play(c.end);
}

export function initHighlights() {
  const root = $("#highlights-panel");
  const minS = el("input", { type: "number", id: "hl-min", min: 10, max: 300, value: recall("vidcut.hlMin", 30) });
  const maxS = el("input", { type: "number", id: "hl-max", min: 15, max: 600, value: recall("vidcut.hlMax", 90) });
  const results = el("div", { class: "hl-results" });
  const words = {};
  const wordBox = el("details", { class: "hl-words" }, el("summary", {}, "Word lists (edit to suit the teacher)"));
  const aiAnswer = el("textarea", { id: "hl-answer", rows: 4, placeholder: "Paste the AI's answer here, e.g.\n12:30-13:45 | scold | reason" });

  const lexicon = () => Object.fromEntries(Object.entries(words).map(([k, t]) => [k, t.value.split(/[,\n]/).map((w) => w.trim()).filter(Boolean)]));

  async function loadWords() {
    let saved = null;
    try { saved = JSON.parse(recall("vidcut.hlWords", "null")); } catch { /* ignore a damaged saved list */ }
    const { lexicon: defaults } = await api("GET", "/api/highlights/lexicon");
    for (const [k, label] of [["scold", "Scolding words"], ["wisdom", "Wake-up call words"], ["funny", "Funny words"]]) {
      words[k] = el("textarea", { rows: 3, "aria-label": label });
      words[k].value = (saved?.[k] ?? defaults[k]).join(", ");
      words[k].addEventListener("change", () => remember("vidcut.hlWords", JSON.stringify(lexicon())));
      wordBox.append(el("label", { class: "field" }, el("span", {}, label), words[k]));
    }
  }

  function show(cands) {
    results.replaceChildren(...ORDER.flatMap((cat) => {
      const rows = cands.filter((c) => c.category === cat);
      if (!rows.length) return [];
      return [el("h3", {}, LABELS[cat]), ...rows.map((c) => el("div", { class: "hl-row", "data-cat": cat },
        el("div", { class: "row" }, el("strong", {}, `${fmtTime(c.start)} – ${fmtTime(c.end)}`),
          el("span", { class: "muted small" }, `${Math.round(c.end - c.start)} s${c.hits ? ` · ${c.hits} hits` : ""}`), el("span", { class: "spacer" }),
          el("button", { class: "ghost small", onclick: () => preview(c) }, "Preview"),
          el("button", { class: "small", onclick: () => useRange(c) }, "Use as In/Out")),
        el("div", { class: "muted small hl-text" }, c.text || ""))) ];
    }));
    if (!cands.length) results.replaceChildren(el("p", { class: "muted small" }, "Nothing found."));
  }

  const scan = el("button", { id: "btn-scan-hl", class: "primary", onclick: async () => {
    remember("vidcut.hlMin", minS.value); remember("vidcut.hlMax", maxS.value);
    try {
      const r = await withSavedProject(() => api("POST", "/api/highlights", { min_s: +minS.value, max_s: +maxS.value, lexicon: lexicon() }));
      show(r.candidates);
    } catch (e) { showError(e); }
  } }, "Scan subtitles");

  const copyBtn = el("button", { id: "btn-copy-transcript", onclick: async () => {
    try {
      const r = await withSavedProject(() => api("GET", "/api/highlights/transcript"));
      try {
        await navigator.clipboard.writeText(r.text);
        showToast(`Copied ${r.lines} lines with instructions. Paste it into Claude (or any AI), then paste its answer below.`, "info", 7000);
      } catch {
        const a = el("a", { href: URL.createObjectURL(new Blob([r.text], { type: "text/plain" })), download: "transcript_for_ai.txt" });
        a.click();
        showToast("Couldn't use the clipboard, so the transcript was downloaded as a text file.", "error", 7000);
      }
    } catch (e) { showError(e); }
  } }, "Copy transcript for AI");

  const readBtn = el("button", { id: "btn-read-picks", onclick: () => {
    const picks = parseRanges(aiAnswer.value);
    if (!picks.length) return showToast("No time ranges found. Expected lines like 12:30-13:45 | scold | reason", "error", 6000);
    const total = tm.editedDuration(getProject().clips);
    const inside = picks.filter((r) => r.start < total).map((r) => ({ ...r, end: Math.min(r.end, total) }));
    show(inside.length ? inside : picks);
  } }, "Read AI picks");

  root.replaceChildren(
    el("h2", {}, "Find highlights"),
    el("p", { class: "muted small" }, "Needs subtitles. Scans for scolding, wake-up calls, laughter and energetic stretches, by words and loudness. Free, runs on this computer."),
    el("div", { class: "row" }, el("label", { class: "field" }, el("span", {}, "Min (s)"), minS), el("label", { class: "field" }, el("span", {}, "Max (s)"), maxS)),
    scan, wordBox, results,
    el("h3", {}, "Let an AI choose"),
    el("p", { class: "muted small" }, "Copies the transcript with instructions. Paste it into Claude or another AI (it costs a few tokens of text, not video), then paste the answer back."),
    copyBtn, aiAnswer, readBtn);
  loadWords().catch(showError);
}
