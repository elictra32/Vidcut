// Episode covers: pick a template, type titles, make the covers; they become the Intro clips in order.
import { join } from "node:path";
import { chromium, makeWebm, startApp, must } from "./harness.mjs";

const app = await startApp();
let browser, failed = false;
try {
  const json = { "Content-Type": "application/json" };
  const tpl = join(app.work, "template.webm");
  makeWebm(tpl, 3.1, "sin(2*PI*440*t)", { size: "1920x1080" });
  const main = join(app.work, "main.webm");
  makeWebm(main, 8);
  const add = async (path) => (await (await fetch(`${app.base}/api/clips`, { method: "POST", headers: json, body: JSON.stringify({ path }) })).json()).clip.id;
  const tid = await add(tpl), mid = await add(main);
  const p = (await (await fetch(`${app.base}/api/project`)).json()).project;
  p.clips.forEach((c) => (c.role = c.id === tid ? "intro" : "main"));
  await fetch(`${app.base}/api/project`, { method: "PUT", headers: json, body: JSON.stringify(p) });

  browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  const problems = [];
  page.on("console", (m) => m.type() === "error" && problems.push(m.text()));
  page.on("pageerror", (e) => problems.push(e.message));
  page.on("dialog", (d) => d.accept());
  await page.goto(app.base);
  await page.waitForSelector("#btn-make-covers");
  must((await page.$eval("#cover-template", (s) => s.options.length)) >= 1 && (await page.$eval("#cover-template", (s) => s.value)) === tid, "the template list offers the intro clip");
  await page.fill("#cover-date", "2026-10-22");
  must((await page.inputValue("#cover-date-text")) === "วันที่ 22 ตุลาคม  2569", "picking a date fills in the Thai date text");
  await page.fill("#cover-titles", "Episode One\nEpisode Two | วันที่ 5 พฤศจิกายน  2569");
  await page.click("#btn-make-covers");
  await page.waitForSelector(".toast:has-text('Made 2 cover')", { timeout: 120000 });
  const proj = (await (await fetch(`${app.base}/api/project`)).json()).project;
  const intros = proj.clips.filter((c) => c.role === "intro").map((c) => c.path.split(/[\\/]/).pop());
  must(JSON.stringify(intros) === JSON.stringify(["Episode One.mp4", "Episode Two.mp4"]), "the covers are the Intro clips, in order, replacing the template: " + intros.join(", "));
  must(proj.clips.some((c) => c.id === mid && c.role === "main"), "the main clip is untouched");
  const tags = await page.$$eval(".role-tag", (els) => els.map((e) => e.textContent));
  must(tags.join("|") === "Intro for EP 1|Intro for EP 2", "the clip list labels them for EP 1 and EP 2: " + tags.join(" | "));
  // vertical covers need no template: the template picker is hidden, an intro and an outro of 1080x1920 are drawn
  await page.selectOption("#cover-format", "vertical");
  const opts = await page.$$eval("#cover-title-font option", (o) => o.map((x) => x.value));
  must(opts.includes("Kanit Medium") && opts.includes("Montserrat") && (await page.$eval("#cover-outro-font", (s) => s.value)) === "Prompt Light", `the font lists are filled (${opts.length} fonts) with the brand fonts selected`);
  must(!(await page.isVisible("#cover-template")) && await page.isVisible("#cover-outro-text"), "the vertical style hides the template picker and offers the back cover");
  await page.waitForSelector("#cover-preview-back:not([hidden])", { timeout: 30000 });
  const src1 = await page.$eval("#cover-preview-front", (i) => i.src);
  must(await page.isVisible("#cover-preview-back"), "the vertical style previews the front and the back cover without making any clip");
  await page.click("#covers-panel summary:has-text(\"Fonts\")");
  await page.selectOption("#cover-title-font", "Kanit Medium");
  await page.waitForFunction((a) => document.querySelector("#cover-preview-front").src !== a, src1, { timeout: 20000 });
  must(true, "choosing another font redraws the preview");
  await page.click("#cover-preview-front");
  await page.waitForSelector("dialog.cover-dialog img.cover-big", { timeout: 5000 });
  must(await page.$eval("dialog.cover-dialog img.cover-big", (i) => i.naturalWidth > 500 && i.getBoundingClientRect().height > 400), "clicking the preview opens it large");
  await page.keyboard.press("Escape");
  await page.waitForSelector("dialog.cover-dialog", { state: "detached", timeout: 5000 });
  must(true, "Esc closes the large preview");
  await page.fill("#cover-titles", "Vertical One");
  await page.click("#btn-make-covers");
  await page.waitForSelector(".toast:has-text('Made 1 cover')", { timeout: 120000 });
  const vp = (await (await fetch(`${app.base}/api/project`)).json()).project;
  const vc = vp.clips.filter((c) => c.role !== "main");
  must(vc.map((c) => c.role).join() === "intro,outro" && vc.every((c) => c.width === 1080 && c.height === 1920), "a vertical intro and outro (1080x1920) were made");
  // a cover can be opened from the clip list and played on its own (it used to jump back to the main video)
  await page.locator(".clip-list li", { hasText: "Intro for EP 1" }).locator(".clip-main").click();
  await page.waitForTimeout(600);
  const shown = await page.evaluate(async () => (await import("/player.js")).getSourceTime());
  must(shown > 1.5, `opening a cover shows it with its texts on screen, not the empty first frame (at ${shown.toFixed(1)} s)`);
  await page.click("button.primary:has-text(\"Play\")");
  await page.waitForTimeout(1200);
  const seen = await page.evaluate(async () => { const pl = await import("/player.js"); return { id: pl.getLoadedClipId(), t: pl.getSourceTime(), playing: pl.isPlaying() }; });
  const introId = (await (await fetch(`${app.base}/api/project`)).json()).project.clips.find((c) => c.role === "intro").id;
  must(seen.id === introId && seen.t > 0.3, `Play plays the cover itself (clip ${seen.id}, at ${seen.t.toFixed(1)} s)`);
  await page.waitForTimeout(2600);
  // Space right after clicking a cover (the clip button still has focus) plays the cover and does not wander off to the main video
  await page.locator(".clip-list li", { hasText: "Intro for EP 1" }).locator(".clip-main").click();
  await page.waitForTimeout(500);
  await page.keyboard.press("Space");
  await page.waitForTimeout(1000);
  const sp = await page.evaluate(async () => { const pl = await import("/player.js"); return { id: pl.getLoadedClipId(), t: pl.getSourceTime(), playing: pl.isPlaying() }; });
  must(sp.id === introId && sp.playing && sp.t > 0.3 && sp.t < 2.2, `Space plays the cover from its start and stays on it (${JSON.stringify({ ...sp, t: +sp.t.toFixed(1) })})`);
  await page.waitForTimeout(2600);
  must(!(await page.evaluate(async () => (await import("/player.js")).isPlaying())), "it stops at the end of the cover");
  must(problems.length === 0, "no console errors" + (problems.length ? ": " + problems.join(" | ") : ""));
} catch (e) {
  failed = true;
  console.error("FAIL:", e.message);
  if (app.log()) console.error("server log:\n" + app.log().slice(-1500));
} finally {
  await browser?.close();
  app.stop();
}
process.exit(failed ? 1 : 0);
