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
  must(!(await page.isVisible("#cover-template")) && await page.isVisible("#cover-outro-text"), "the vertical style hides the template picker and offers the back cover");
  await page.fill("#cover-titles", "Vertical One");
  await page.click("#btn-make-covers");
  await page.waitForSelector(".toast:has-text('Made 1 cover')", { timeout: 120000 });
  const vp = (await (await fetch(`${app.base}/api/project`)).json()).project;
  const vc = vp.clips.filter((c) => c.role !== "main");
  must(vc.map((c) => c.role).join() === "intro,outro" && vc.every((c) => c.width === 1080 && c.height === 1920), "a vertical intro and outro (1080x1920) were made");
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
