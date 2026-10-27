// Find highlight moments for short clips: a free local scan (word lists + loudness), and a hand-off to an AI
// (copy the transcript with a ready prompt, paste its answer back).
import { api } from "./api.js";
import { getProject, update, withSavedProject } from "./state.js";
import { makeReel } from "./cut_tools.js";
import { addToQueue } from "./queue_panel.js";
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

  let shots = false;
  const checkedRows = () => [...results.querySelectorAll(".hl-pick:checked")].map((b) => b.closest(".hl-row"));
  const reelBtn = el("button", { id: "btn-make-reel", class: "primary", hidden: true, onclick: () => makeReel(checkedRows().map((r) => ({ start: +r.dataset.start, end: +r.dataset.end }))) });
  const withExtras = el("input", { type: "checkbox", id: "hl-extras" });
  const maxMb = el("input", { type: "number", id: "hl-max-mb", min: 1, step: 1, class: "num", placeholder: "no limit", value: recall("vidcut.hlMaxMb", ""), "aria-label": "Largest size of each clip in megabytes" });
  maxMb.addEventListener("change", () => remember("vidcut.hlMaxMb", maxMb.value));
  const exportBtn = el("button", { id: "btn-export-highlights", hidden: true, title: "Each checked highlight becomes its own video file; they run one after another in the queue", onclick: async () => {
    const ranges = checkedRows().map((r) => ({ start: +r.dataset.start, end: +r.dataset.end, label: r.dataset.cat }));
    if (ranges.length) await addToQueue("highlights", { ranges, with_extras: withExtras.checked, max_mb: maxMb.value ? +maxMb.value : null });
  } });
  const exportBox = el("div", { hidden: true },
    el("label", { class: "row small" }, withExtras, el("span", {}, "Add the intro/outro clips to each")),
    el("label", { class: "row small" }, el("span", {}, "Largest size per clip (MB)"), maxMb),
    exportBtn);
  const count = () => {
    const n = results.querySelectorAll(".hl-pick:checked").length;
    const any = results.querySelector(".hl-pick") !== null;
    reelBtn.hidden = !any;
    exportBox.hidden = exportBtn.hidden = !any;
    reelBtn.disabled = exportBtn.disabled = !n;
    reelBtn.textContent = `Make one reel from ${n} checked`;
    exportBtn.textContent = `Export ${n} checked as separate clips`;
  };

  function show(cands, asShots = false) {
    shots = asShots;
    results.replaceChildren(...ORDER.flatMap((cat) => {
      const rows = cands.filter((c) => c.category === cat);
      if (!rows.length) return [];
      const all = el("input", { type: "checkbox", class: "hl-all", "aria-label": `Select all ${LABELS[cat]}`, checked: shots,
        onchange: () => results.querySelectorAll(`.hl-row[data-cat="${cat}"] .hl-pick`).forEach((b) => { b.checked = all.checked; count(); }) });
      return [el("div", { class: "row" }, all, el("h3", {}, `${LABELS[cat]} (${rows.length})`)),
        ...rows.map((c) => el("div", { class: "hl-row", "data-cat": cat, "data-start": c.start, "data-end": c.end },
        el("div", { class: "row" }, el("input", { type: "checkbox", class: "hl-pick", checked: shots, "aria-label": "Include this highlight", onchange: count }),
          el("strong", {}, `${fmtTime(c.start)} – ${fmtTime(c.end)}`),
          el("span", { class: "muted small" }, `${Math.round(c.end - c.start)} s${c.hits ? ` · ${c.hits} hits` : ""}`), el("span", { class: "spacer" }),
          el("button", { class: "ghost small", onclick: () => preview(c) }, "Preview"),
          el("button", { class: "small", onclick: () => useRange(c) }, "Use as In/Out")),
        el("div", { class: "muted small hl-text" }, c.text || ""))) ];
    }));
    if (!cands.length) results.replaceChildren(el("p", { class: "muted small" }, "Nothing found."));
    count();
  }

  const scan = el("button", { id: "btn-scan-hl", class: "primary", onclick: async () => {
    remember("vidcut.hlMin", minS.value); remember("vidcut.hlMax", maxS.value);
    try {
      const r = await withSavedProject(() => api("POST", "/api/highlights", { min_s: +minS.value, max_s: +maxS.value, lexicon: lexicon() }));
      show(r.candidates);
    } catch (e) { showError(e); }
  } }, "Scan subtitles");

  const reelScan = el("button", { id: "btn-scan-shots", onclick: async () => {
    try {
      const r = await withSavedProject(() => api("POST", "/api/highlights", { mode: "shots", lexicon: lexicon() }));
      show(r.candidates, true);
      showToast(`${r.candidates.length} short shots found. Untick any you don't want, then make the reel.`, "info", 5000);
    } catch (e) { showError(e); }
  } }, "Find short shots (for a reel)");

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
    el("p", { class: "muted small" }, "Needs subtitles. \"Find short shots\" lists every scolding / wake-up / funny moment of the whole clip so you can gather them into one reel. Scans for scolding, wake-up calls, laughter and energetic stretches, by words and loudness. Free, runs on this computer."),
    el("div", { class: "row" }, el("label", { class: "field" }, el("span", {}, "Min (s)"), minS), el("label", { class: "field" }, el("span", {}, "Max (s)"), maxS)),
    scan, reelScan, wordBox, reelBtn, exportBox, results,
    el("h3", {}, "Let an AI choose"),
    el("p", { class: "muted small" }, "Copies the transcript with instructions. Paste it into Claude or another AI (it costs a few tokens of text, not video), then paste the answer back."),
    copyBtn, aiAnswer, readBtn);
  loadWords().catch(showError);
}
