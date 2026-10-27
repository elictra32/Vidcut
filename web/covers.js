// Make episode covers: copy the look of a template cover clip, with a new title and date for each episode.
import { api } from "./api.js";
import { getFonts, getProject, loadProject, subscribe, withSavedProject } from "./state.js";
import { trackJob } from "./status.js";
import { showError, showToast } from "./toast.js";
import { $, basename, el, recall, remember } from "./util.js";

const MONTHS = ["มกราคม", "กุมภาพันธ์", "มีนาคม", "เมษายน", "พฤษภาคม", "มิถุนายน", "กรกฎาคม", "สิงหาคม", "กันยายน", "ตุลาคม", "พฤศจิกายน", "ธันวาคม"];
export const thaiDate = (iso) => {
  const [y, m, d] = iso.split("-").map(Number);
  return `วันที่ ${d} ${MONTHS[m - 1]}  ${y + 543}`; // Buddhist-era year, two spaces before it as in the sample covers
};

/** Lines of "Title" or "Title | date text" -> [{ title, date_text? }]. */
export function parseTitles(text) {
  return text.split(/\r?\n/).map((l) => l.trim()).filter(Boolean).map((l) => {
    const [title, ...rest] = l.split("|");
    const date_text = rest.join("|").trim();
    return { title: title.trim(), ...(date_text ? { date_text } : {}) };
  }).filter((it) => it.title);
}

export function initCovers() {
  const root = $("#covers-panel");
  const template = el("select", { id: "cover-template" });
  const today = new Date();
  const iso = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}-${String(today.getDate()).padStart(2, "0")}`;
  const date = el("input", { type: "date", id: "cover-date", value: iso });
  const dateText = el("input", { type: "text", id: "cover-date-text", value: thaiDate(iso) });
  date.addEventListener("change", () => date.value && (dateText.value = thaiDate(date.value)));
  const titles = el("textarea", { id: "cover-titles", rows: 5, placeholder: "One episode title per line, e.g.\nCandlestick and Price Pattern II P1\nCandlestick and Price Pattern II P2\n\nTo give one episode its own date: Title | วันที่ 5 พฤศจิกายน  2569" });
  titles.value = recall("vidcut.coverTitles", "");
  titles.addEventListener("change", () => remember("vidcut.coverTitles", titles.value));
  const replace = el("input", { type: "checkbox", id: "cover-replace", checked: true });
  // the font list arrives with the project (after this panel is built), so the options are filled in on every load
  const titleFont = el("select", { id: "cover-title-font" }), dateFont = el("select", { id: "cover-date-font" }), outroFont = el("select", { id: "cover-outro-font" });
  const FONT_SELECTS = [[titleFont, "T", "Montserrat"], [dateFont, "D", "Prompt Light"], [outroFont, "O", "Prompt Light"]];
  for (const [sel, key] of FONT_SELECTS) sel.addEventListener("change", () => remember(`vidcut.coverFont${key}`, sel.value));
  const fillFonts = () => {
    const fonts = getFonts();
    if (!fonts.length) return;
    for (const [sel, key, fallback] of FONT_SELECTS) {
      const want = sel.value || recall(`vidcut.coverFont${key}`, "") || fallback;
      sel.replaceChildren(...fonts.map((f) => el("option", { value: f, style: `font-family: "${f}"` }, f)));
      sel.value = fonts.includes(want) ? want : fonts.includes(fallback) ? fallback : fonts[0];
    }
  };
  const format = el("select", { id: "cover-format" }, el("option", { value: "landscape" }, "Landscape: copy the look of one of your covers"),
    el("option", { value: "vertical" }, "Vertical (TikTok 1080×1920): drawn by Vidcut"));
  format.value = recall("vidcut.coverFormat", "landscape");
  const withOutro = el("input", { type: "checkbox", id: "cover-outro", checked: true });
  const outroText = el("textarea", { id: "cover-outro-text", rows: 3 });
  const introSound = el("select", { id: "cover-intro-sound" }), outroSound = el("select", { id: "cover-outro-sound" });
  outroText.value = recall("vidcut.coverOutroText2", "ขอบคุณที่รับชม\nติดตาม THUS ไว้\nไม่พลาดตอนต่อไป");
  outroText.addEventListener("change", () => remember("vidcut.coverOutroText2", outroText.value));
  const templateField = el("label", { class: "field" }, el("span", {}, "Copy the look of"), template);
  const verticalBox = el("div", { class: "vertical-only" },
    el("p", { class: "muted small" }, "Draws the front cover in the THUS colours (logo, title in orange on a black box, date), kept clear of TikTok's buttons and captions. Set the preset to TikTok before exporting."),
    el("label", { class: "field inline" }, el("span", {}, "Also make a matching back cover (outro)"), withOutro),
    el("label", { class: "field" }, el("span", {}, "Back cover text (one line each)"), outroText),
    el("label", { class: "field" }, el("span", {}, "Sound of the front cover"), introSound),
    el("label", { class: "field" }, el("span", {}, "Sound of the back cover"), outroSound),
    el("p", { class: "muted small" }, "The sound is taken from a clip in this project (for example your landscape intro or outro), from its start, faded out at the end. (silence) = no sound."));
  const fillSounds = () => {
    const clips = (getProject()?.clips ?? []).filter((c) => c.has_audio);
    const label = (c) => `${basename(c.path)}${(c.role ?? "main") === "main" ? "" : ` (${c.role})`}`;
    for (const [sel, role] of [[introSound, "intro"], [outroSound, "outro"]]) {
      const keep = sel.value;
      sel.replaceChildren(el("option", { value: "" }, "(silence)"), ...clips.map((c) => el("option", { value: c.id }, label(c))));
      // by default take the sound of the cover you already have (your landscape intro / outro), if there is one
      const first = clips.find((c) => c.role === role) ?? (role === "outro" ? null : clips.find((c) => c.role === "intro"));
      sel.value = clips.some((c) => c.id === keep) || keep === "" && sel.dataset.touched ? keep : first?.id ?? "";
    }
  };
  for (const sel of [introSound, outroSound]) sel.addEventListener("change", () => (sel.dataset.touched = "1"));
  const syncFormat = () => {
    const v = format.value === "vertical";
    templateField.hidden = v;
    verticalBox.hidden = !v;
    remember("vidcut.coverFormat", format.value);
  };
  format.addEventListener("change", syncFormat);
  const make = el("button", { id: "btn-make-covers", class: "primary" }, "Make covers");

  const fillTemplates = () => {
    const p = getProject();
    const cands = (p?.clips ?? []).filter((c) => (c.role ?? "main") === "intro" || c.duration <= 6);
    const keep = template.value;
    template.replaceChildren(...(cands.length ? cands : [null]).map((c) => c
      ? el("option", { value: c.id }, basename(c.path)) : el("option", { value: "" }, "(add a cover clip first)")));
    if (cands.some((c) => c.id === keep)) template.value = keep;
  };

  // ---- live preview: one quick picture of the cover with the current title, date and fonts ----
  const imgFront = el("img", { id: "cover-preview-front", class: "cover-preview-img", alt: "Front cover preview", hidden: true });
  const imgBack = el("img", { id: "cover-preview-back", class: "cover-preview-img", alt: "Back cover preview", hidden: true });
  const previewNote = el("p", { class: "muted small", id: "cover-preview-note" });
  const previewBox = el("div", { class: "cover-preview" }, el("div", { class: "row" }, imgFront, imgBack), previewNote);
  let previewTimer = null, previewSeq = 0;
  const fetchPng = async (body) => {
    const res = await fetch("/api/covers/preview", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    if (!res.ok) throw new Error((await res.json().catch(() => null))?.error?.message ?? `HTTP ${res.status}`);
    return URL.createObjectURL(await res.blob());
  };
  const refreshPreview = () => {
    clearTimeout(previewTimer);
    previewTimer = setTimeout(async () => {
      const seq = ++previewSeq;
      const vertical = format.value === "vertical";
      const tplClip = getProject()?.clips.find((c) => c.id === template.value);
      if (!vertical && !tplClip) { imgFront.hidden = imgBack.hidden = true; previewNote.textContent = "Add a cover clip to preview the look."; return; }
      // only the THUS template shape can be drawn on (see core/cover.py check_template): don't ask the server for anything else
      if (!vertical && !(tplClip.width === 1920 && tplClip.height === 1080 && tplClip.duration >= 2.5 && tplClip.duration <= 4)) {
        imgFront.hidden = imgBack.hidden = true;
        previewNote.textContent = "No preview: this clip is not a THUS cover template (1920×1080, about 3 seconds).";
        return;
      }
      previewNote.textContent = "Drawing the preview…";
      const base = { format: vertical ? "vertical" : "landscape", template_clip_id: template.value, title: parseTitles(titles.value)[0]?.title || "Episode title",
        date_text: dateText.value.trim(), title_font: titleFont.value, date_font: dateFont.value, outro_font: outroFont.value, outro_text: outroText.value };
      try {
        const front = await fetchPng({ ...base, kind: "intro" });
        const back = vertical && withOutro.checked ? await fetchPng({ ...base, kind: "outro" }) : null;
        if (seq !== previewSeq) return (URL.revokeObjectURL(front), back && URL.revokeObjectURL(back));
        for (const [img, url] of [[imgFront, front], [imgBack, back]]) {
          if (img.src.startsWith("blob:")) URL.revokeObjectURL(img.src);
          if (url) img.src = url; else img.removeAttribute("src");
          img.hidden = !url;
        }
        previewNote.textContent = "Preview of the cover at its end (the real clip fades its texts in).";
      } catch (e) {
        if (seq === previewSeq) previewNote.textContent = `Couldn't draw the preview: ${e.message}`;
      }
    }, 600);
  };
  for (const c of [titles, dateText, date, template, format, titleFont, dateFont, outroFont, outroText, withOutro]) {
    c.addEventListener("input", refreshPreview);
    c.addEventListener("change", refreshPreview);
  }

  make.addEventListener("click", async () => {
    const items = parseTitles(titles.value);
    const vertical = format.value === "vertical";
    if (!vertical && !template.value) return showToast("Add one of your existing cover clips first (set its role to Intro): the new covers copy its look", "error", 6000);
    if (!items.length) return showToast("Type at least one episode title", "error");
    if (!dateText.value.trim()) return showToast("Type the date text, or pick a date", "error");
    if (replace.checked && !confirm(`Make ${items.length} cover(s) and replace the current Intro clips in the project? (Your files are not deleted.)`)) return;
    make.disabled = true;
    try {
      const { job } = await withSavedProject(() => api("POST", "/api/covers", {
        format: vertical ? "vertical" : "landscape", with_outro: withOutro.checked, outro_text: outroText.value,
        intro_sound_clip_id: introSound.value || null, outro_sound_clip_id: outroSound.value || null,
        template_clip_id: template.value, items, date_text: dateText.value.trim(), replace_intros: replace.checked,
        title_font: titleFont.value, date_font: dateFont.value, outro_font: outroFont.value }));
      const done = await trackJob("Making covers", job);
      if (!done) return;
      await loadProject();
      showToast(`Made ${done.result.count} cover(s). They are the Intro clips now, in order (saved in ${done.result.dir}).`, "info", 8000);
    } catch (e) {
      showError(e);
    } finally {
      make.disabled = false;
    }
  });

  root.replaceChildren(
    el("h2", {}, "Episode covers"),
    el("p", { class: "muted small" }, "Copies the look of one of your cover clips (the THUS template) and puts a new title and date on it: one cover per line."),
    el("label", { class: "field" }, el("span", {}, "Cover style"), format),
    templateField, verticalBox,
    el("label", { class: "field" }, el("span", {}, "Date"), date),
    el("label", { class: "field" }, el("span", {}, "Date text on the cover"), dateText),
    el("label", { class: "field" }, el("span", {}, "Episode titles"), titles),
    el("label", { class: "field inline" }, el("span", {}, "Replace the current Intro (and Outro) clips"), replace),
    el("details", {}, el("summary", {}, "Fonts"),
      el("label", { class: "field" }, el("span", {}, "Title (front cover)"), titleFont), el("label", { class: "field" }, el("span", {}, "Date (front cover)"), dateFont),
      el("label", { class: "field" }, el("span", {}, "Text of the back cover"), outroFont),
      el("p", { class: "muted small" }, "Each font name is shown in its own style. All of them draw Thai and English.")),
    previewBox,
    make);
  subscribe((why) => { if (why === "load") { fillFonts(); refreshPreview(); } if (why === "load" || why === "keeps" || why === "edit") { fillTemplates(); fillSounds(); } });
  fillTemplates();
  fillFonts();
  fillSounds();
  syncFormat();
  refreshPreview();
}
