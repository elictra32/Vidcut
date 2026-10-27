// Undo / redo: Ctrl+Z, Ctrl+Y and the header buttons bring back deleted subtitles, cuts and style changes.
import { join } from "node:path";
import { chromium, makeWebm, startApp, must, sleep } from "./harness.mjs";

const app = await startApp();
let browser, failed = false;
try {
  const clip = join(app.work, "a.webm");
  makeWebm(clip, 12);
  const json = { "Content-Type": "application/json" };
  const added = await (await fetch(`${app.base}/api/clips`, { method: "POST", headers: json, body: JSON.stringify({ path: clip }) })).json();
  const p = (await (await fetch(`${app.base}/api/project`)).json()).project;
  p.subtitles = ["หนึ่ง", "สอง", "สาม"].map((t, i) => ({ id: `s${i}`, clip_id: added.clip.id, src_start: i * 3, src_end: i * 3 + 2, text: t, x: null, y: null }));
  await fetch(`${app.base}/api/project`, { method: "PUT", headers: json, body: JSON.stringify(p) });
  const server = async () => (await (await fetch(`${app.base}/api/project`)).json()).project;

  browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  const problems = [];
  page.on("console", (m) => m.type() === "error" && problems.push(m.text()));
  page.on("pageerror", (e) => problems.push(e.message));
  page.on("dialog", (d) => d.accept());
  await page.goto(app.base);
  await page.waitForSelector(".sub-row");
  must(await page.isDisabled("#btn-undo"), "Undo is disabled before any edit");

  await page.click("#btn-delete-all-subs");
  await page.waitForSelector(".sub-list .sub-row", { state: "detached" });
  must(!(await page.isDisabled("#btn-undo")), "Undo is enabled after an edit");
  await page.click("#btn-undo");
  await page.waitForSelector(".sub-row");
  must((await page.$$(".sub-row")).length === 3, "Undo brings the deleted subtitles back");
  await sleep(700);
  must((await server()).subtitles.length === 3, "the restored subtitles are saved to the server");
  must(!(await page.isDisabled("#btn-redo")), "Redo is enabled after an undo");
  await page.keyboard.press("Control+y");
  await page.waitForSelector(".sub-list .sub-row", { state: "detached" });
  must(true, "Ctrl+Y redoes the deletion");
  await page.keyboard.press("Control+z");
  await page.waitForSelector(".sub-row");
  must((await page.$$(".sub-row")).length === 3, "Ctrl+Z undoes it again");

  // a slider drag is one undo step, not one per pixel
  const size = page.locator("#style-panel input[type=range]").first();
  const before = (await server()).style.size;
  for (const v of [70, 80, 90, 100]) { await size.evaluate((i, val) => { i.value = val; i.dispatchEvent(new Event("input")); }, v); }
  await sleep(700);
  await page.keyboard.press("Control+z");
  await sleep(700);
  must((await server()).style.size === before, `one Ctrl+Z undoes the whole slider drag (size back to ${before})`);

  // typing in a text box keeps the browser's own undo and does not trigger ours
  await page.locator(".sub-row textarea").first().click();
  const n = await page.evaluate(() => document.querySelectorAll(".sub-row").length);
  await page.keyboard.press("Control+z");
  must((await page.$$(".sub-row")).length === n, "Ctrl+Z inside a text box is left to the text box");
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
