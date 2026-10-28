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

/**
 * The covers to make, from the list on screen: [{ title, date }] -> [{ title, date_text? }]. A title keeps its own line breaks
 * (Enter inside a title = a new line ON that cover); blank lines and empty covers are dropped.
 */
export function cleanItems(items) {
  return items.map((it) => {
    const title = String(it.title ?? "").split(/\r?\n/).map((l) => l.trim().replace(/\s+/g, " ")).filter(Boolean).join("\n");
    const date_text = String(it.date ?? "").trim();
    return { title, ...(date_text ? { date_text } : {}) };
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
  // one box per cover: Enter inside a box breaks the line on that cover; "+ Add another cover" makes one more clip
  let items = [{ title: "", date: "" }];
  try {
    const saved = JSON.parse(recall("vidcut.coverItems", "null"));
    if (Array.isArray(saved) && saved.length) items = saved.map((x) => ({ title: String(x.title ?? ""), date: String(x.date ?? "") }));
  } catch { /* a damaged saved list: start with one empty cover */ }
  const itemsBox = el("div", { id: "cover-items" });
  const saveItems = () => remember("vidcut.coverItems", JSON.stringify(items));
  const renderItems = () => {
    itemsBox.replaceChildren(...items.map((it, i) => {
      const ta = el("textarea", { class: "cover-title", rows: 2, "aria-label": `Title of cover ${i + 1}`,
        placeholder: "Title of this cover. Press Enter to start a new line on the cover." });
      if (i === 0) ta.id = "cover-titles";
      ta.value = it.title;
      ta.addEventListener("input", () => { it.title = ta.value; saveItems(); });
      const dt = el("input", { type: "text", class: "cover-item-date", "aria-label": `Date text of cover ${i + 1}`, placeholder: "Own date text (empty = the date above)", value: it.date });
      dt.addEventListener("input", () => { it.date = dt.value; saveItems(); });
      for (const c of [ta, dt]) { c.addEventListener("input", () => refreshPreview()); }
      return el("div", { class: "cover-item", "data-i": i },
        el("div", { class: "row" }, el("strong", { class: "small" }, `Cover ${i + 1}`), el("span", { class: "spacer" }),
          items.length > 1 ? el("button", { class: "ghost icon cover-remove", title: "Remove this cover", onclick: () => { items.splice(i, 1); saveItems(); renderItems(); refreshPreview(); } }, "✕") : ""),
        ta, dt);
    }), el("button", { id: "btn-add-cover", class: "small", onclick: () => { items.push({ title: "", date: "" }); saveItems(); renderItems(); itemsBox.querySelector(".cover-item:last-of-type textarea")?.focus(); } }, "+ Add another cover"));
  };
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
    el("button", { class: "ghost small", id: "btn-pick-intro-sound", onclick: () => chooseSound(introSound)() }, "Choose a sound file for the front…"),
    el("label", { class: "field" }, el("span", {}, "Sound of the back cover"), outroSound),
    el("button", { class: "ghost small", id: "btn-pick-outro-sound", onclick: () => chooseSound(outroSound)() }, "Choose a sound file for the back…"),
    el("p", { class: "muted small" }, "The sound comes from a clip in this project (for example your landscape intro or outro) or from any sound/video file you choose, from its start, faded out at the end. (silence) = no sound. The covers Vidcut drew itself have no real sound."));
  const fillSounds = () => {
    const clips = (getProject()?.clips ?? []).filter((c) => c.has_audio);
    const label = (c) => `${basename(c.path)}${(c.role ?? "main") === "main" ? "" : ` (${c.role})`}`;
    // the covers Vidcut drew itself are silent: they are listed but never the default source of a sound
    const real = clips.filter((c) => !/_vertical\.mp4$|^THUS_outro_vertical/i.test(basename(c.path)));
    for (const [sel, role] of [[introSound, "intro"], [outroSound, "outro"]]) {
      const keep = sel.value;
      const custom = [...sel.querySelectorAll("option[data-file]")];   // a file picked from the disk stays offered
      sel.replaceChildren(el("option", { value: "" }, "(silence)"), ...clips.map((c) => el("option", { value: c.id }, label(c))), ...custom);
      const first = real.find((c) => c.role === role) ?? (role === "outro" ? null : real.find((c) => c.role === "intro"));
      const stillThere = clips.some((c) => c.id === keep) || custom.some((o) => o.value === keep);
      sel.value = stillThere || (keep === "" && sel.dataset.touched) ? keep : first?.id ?? "";
    }
  };
  const chooseSound = (sel) => async () => {
    try {
      const r = await api("POST", "/api/covers/pick-sound");
      if (!r.path) return;
      const value = `file:${r.path}`;
      if (![...sel.options].some((o) => o.value === value)) sel.append(el("option", { value, "data-file": "1" }, `${r.name} (file)`));
      sel.value = value;
      sel.dataset.touched = "1";
    } catch (e) { showError(e); }
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
  // clicking a preview opens it large (click anywhere or press Esc to close)
  for (const img of [imgFront, imgBack]) {
    img.title = "Click to see it larger";
    img.addEventListener("click", () => {
      const big = el("img", { class: "cover-big", src: img.src, alt: img.alt });
      const dlg = el("dialog", { class: "frame-dialog cover-dialog" }, big, el("p", { class: "muted small" }, "Click anywhere, or press Esc, to close"));
      dlg.addEventListener("click", () => dlg.close());
      dlg.addEventListener("close", () => dlg.remove());
      document.body.append(dlg);
      dlg.showModal();
    });
  }
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
      const base = { format: vertical ? "vertical" : "landscape", template_clip_id: template.value, title: cleanItems(items)[0]?.title || "Episode title",
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
  for (const c of [dateText, date, template, format, titleFont, dateFont, outroFont, outroText, withOutro]) {
    c.addEventListener("input", refreshPreview);
    c.addEventListener("change", refreshPreview);
  }

  make.addEventListener("click", async () => {
    const covers = cleanItems(items);
    const vertical = format.value === "vertical";
    if (!vertical && !template.value) return showToast("Add one of your existing cover clips first (set its role to Intro): the new covers copy its look", "error", 6000);
    if (!covers.length) return showToast("Type at least one episode title", "error");
    if (!dateText.value.trim()) return showToast("Type the date text, or pick a date", "error");
    if (replace.checked && !confirm(`Make ${covers.length} cover(s) and replace the current Intro clips in the project? (Your files are not deleted.)`)) return;
    make.disabled = true;
    try {
      const { job } = await withSavedProject(() => api("POST", "/api/covers", {
        format: vertical ? "vertical" : "landscape", with_outro: withOutro.checked, outro_text: outroText.value,
        intro_sound_clip_id: introSound.value || null, outro_sound_clip_id: outroSound.value || null,
        template_clip_id: template.value, items: covers, date_text: dateText.value.trim(), replace_intros: replace.checked,
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
    el("div", { class: "field" }, el("span", {}, "Cover titles (one box per cover)"), itemsBox),
    el("label", { class: "field inline" }, el("span", {}, "Replace the current Intro (and Outro) clips"), replace),
    el("details", {}, el("summary", {}, "Fonts"),
      el("label", { class: "field" }, el("span", {}, "Title (front cover)"), titleFont), el("label", { class: "field" }, el("span", {}, "Date (front cover)"), dateFont),
      el("label", { class: "field" }, el("span", {}, "Text of the back cover"), outroFont),
      el("p", { class: "muted small" }, "Each font name is shown in its own style. All of them draw Thai and English.")),
    previewBox,
    make);
  subscribe((why) => { if (why === "load") { fillFonts(); refreshPreview(); } if (why === "load" || why === "keeps" || why === "edit") { fillTemplates(); fillSounds(); } });
  fillTemplates();
  renderItems();
  fillFonts();
  fillSounds();
  syncFormat();
  refreshPreview();
}
