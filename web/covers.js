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
  const fontSel = (id, value) => {
    const s = el("select", { id }, getFonts().map((f) => el("option", { value: f }, f)));
    s.value = value;
    return s;
  };
  const titleFont = fontSel("cover-title-font", "Montserrat"), dateFont = fontSel("cover-date-font", "Prompt Light");
  const format = el("select", { id: "cover-format" }, el("option", { value: "landscape" }, "Landscape: copy the look of one of your covers"),
    el("option", { value: "vertical" }, "Vertical (TikTok 1080×1920): drawn by Vidcut"));
  format.value = recall("vidcut.coverFormat", "landscape");
  const withOutro = el("input", { type: "checkbox", id: "cover-outro", checked: true });
  const outroText = el("textarea", { id: "cover-outro-text", rows: 3 });
  outroText.value = recall("vidcut.coverOutroText2", "ขอบคุณที่รับชม\nติดตาม THUS ไว้\nไม่พลาดตอนต่อไป");
  outroText.addEventListener("change", () => remember("vidcut.coverOutroText2", outroText.value));
  const templateField = el("label", { class: "field" }, el("span", {}, "Copy the look of"), template);
  const verticalBox = el("div", { class: "vertical-only" },
    el("p", { class: "muted small" }, "Draws the front cover in the THUS colours (logo, title in orange on a black box, date), kept clear of TikTok's buttons and captions. Set the preset to TikTok before exporting."),
    el("label", { class: "field inline" }, el("span", {}, "Also make a matching back cover (outro)"), withOutro),
    el("label", { class: "field" }, el("span", {}, "Back cover text (one line each)"), outroText));
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
        template_clip_id: template.value, items, date_text: dateText.value.trim(), replace_intros: replace.checked,
        title_font: titleFont.value, date_font: dateFont.value }));
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
      el("label", { class: "field" }, el("span", {}, "Title"), titleFont), el("label", { class: "field" }, el("span", {}, "Date"), dateFont)),
    make);
  subscribe((why) => (why === "load" || why === "keeps" || why === "edit") && fillTemplates());
  fillTemplates();
  syncFormat();
}
