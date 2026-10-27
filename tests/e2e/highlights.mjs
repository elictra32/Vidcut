// Highlights: local scan finds the scolding stretch, "Use as In/Out" sets the selection, AI answers are parsed.
import { join } from "node:path";
import { chromium, makeWebm, startApp, must } from "./harness.mjs";

const app = await startApp();
let browser, failed = false;
try {
  const clip = join(app.work, "a.webm");
  makeWebm(clip, 90);
  const json = { "Content-Type": "application/json" };
  const added = await (await fetch(`${app.base}/api/clips`, { method: "POST", headers: json, body: JSON.stringify({ path: clip }) })).json();
  const p = (await (await fetch(`${app.base}/api/project`)).json()).project;
  const texts = Array.from({ length: 30 }, (_, i) => (i >= 10 && i < 14 ? "ไอ้โง่ ไม่ได้เรื่อง ขี้เกียจ" : "วันนี้เรียนเรื่องบัญชี"));
  p.subtitles = texts.map((t, i) => ({ id: `s${i}`, clip_id: added.clip.id, src_start: i * 3, src_end: i * 3 + 2.5, text: t, x: null, y: null }));
  await fetch(`${app.base}/api/project`, { method: "PUT", headers: json, body: JSON.stringify(p) });

  browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, permissions: ["clipboard-read", "clipboard-write"] });
  const page = await ctx.newPage();
  const problems = [];
  page.on("console", (m) => m.type() === "error" && problems.push(m.text()));
  page.on("pageerror", (e) => problems.push(e.message));
  await page.goto(app.base);
  await page.waitForSelector("#btn-scan-hl");
  await page.fill("#hl-min", "15");
  await page.fill("#hl-max", "30");
  await page.click("#btn-scan-hl");
  await page.waitForSelector('.hl-row[data-cat="scold"]', { timeout: 15000 });
  must(true, "the scan finds a scolding stretch");
  await page.locator('.hl-row[data-cat="scold"] button:has-text("Use as In/Out")').first().click();
  await page.waitForFunction(() => /Selection/.test(document.querySelector(".sel-info")?.textContent ?? ""), null, { timeout: 5000 });
  await page.waitForTimeout(800);
  const saved = await page.evaluate(async () => (await (await fetch("/api/project")).json()).project.selection);
  must(saved && saved.start <= 30 && saved.end >= 41, `Use as In/Out saved the range ${JSON.stringify(saved)}`);

  await page.click("#btn-copy-transcript");
  await page.waitForSelector(".toast", { timeout: 5000 });
  const clip_text = await page.evaluate(() => navigator.clipboard.readText());
  must(/MM:SS-MM:SS/.test(clip_text) && /\[00:30\]/.test(clip_text), "the transcript with instructions is copied");

  await page.fill("#hl-answer", "05:00-05:40 | wisdom | คม\nnot a range\n00:10-00:50 | funny | ขำ");
  await page.click("#btn-read-picks");
  await page.waitForSelector('.hl-row[data-cat="funny"]', { timeout: 5000 });
  must((await page.$$('.hl-row')).length === 1, "only the AI pick inside the timeline is listed (00:10-00:50)");
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
