// Editing from the preview and with typed numbers: double-click a subtitle to edit its text, exact numbers in the
// style boxes, and re-wrapping every subtitle to a number of characters per line.
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
  p.subtitles = [{ id: "s1", clip_id: added.clip.id, src_start: 1, src_end: 7, text: "สวัสดีครับทุกคนวันนี้เรามาตัดต่อวิดีโอกันนะครับ", x: null, y: null }];
  await fetch(`${app.base}/api/project`, { method: "PUT", headers: json, body: JSON.stringify(p) });
  const server = async () => (await (await fetch(`${app.base}/api/project`)).json()).project;

  browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  const problems = [];
  page.on("console", (m) => m.type() === "error" && problems.push(m.text()));
  page.on("pageerror", (e) => problems.push(e.message));
  await page.goto(app.base);
  await page.waitForSelector(".sub-row");
  await sleep(600);
  await page.evaluate(async () => (await import("/player.js")).seek(2.0));
  await page.waitForSelector("#sub-overlay .sub", { timeout: 5000 });

  // 1. edit the text on the preview
  await page.dblclick("#sub-overlay .sub");
  must(await page.$eval("#sub-overlay .sub", (n) => n.isContentEditable), "double-click makes the subtitle editable on the preview");
  await page.keyboard.press("Control+a");
  await page.keyboard.type("พิมพ์แก้บนจอ space i o");
  await page.keyboard.press("Escape");
  await sleep(800);
  must((await server()).subtitles[0].text === "พิมพ์แก้บนจอ space i o", "the text typed on the preview is saved (shortcut keys typed as plain text)");
  must((await page.locator(".sub-row textarea").first().inputValue()) === "พิมพ์แก้บนจอ space i o", "the subtitle list shows the edit");

  // 2. exact numbers in the style panel
  const sizeBox = page.locator("#style-panel .field", { hasText: "Size" }).locator("input.num").first();
  await sizeBox.fill("90");
  await sizeBox.press("Tab");
  await sleep(700);
  must((await server()).style.size === 90, "typing 90 in the Size box sets the subtitle size");
  const xBox = page.locator("#style-panel .field", { hasText: "Horizontal position" }).locator("input.num");
  await xBox.fill("30");
  await xBox.press("Tab");
  await sleep(700);
  must((await server()).style.default_x === 0.3, "typing 30 in the Horizontal position box sets 30%");

  // 3. position typed on a single line, and the box follows a drag on the preview
  const rowX = page.locator('.sub-row input[aria-label^="Horizontal position"]').first();
  await rowX.fill("70");
  await rowX.press("Tab");
  await sleep(700);
  must((await server()).subtitles[0].x === 0.7, "typing 70 in a line's X box moves just that line");

  // 4. re-wrap every subtitle to a number of characters per line
  await page.fill("#rewrap-chars", "8");
  await page.fill("#rewrap-lines", "1");
  await page.click("#btn-rewrap");
  await page.waitForFunction(() => document.querySelectorAll(".sub-row").length > 1, null, { timeout: 8000 });
  const subs = (await server()).subtitles;
  must(subs.length > 1 && subs.every((s) => !s.text.includes("\n")), `re-wrap to 8 characters × 1 line split it into ${subs.length} one-line subtitles`);
  must(subs.every((s) => s.x === 0.7), "the position set on the line is kept on every piece");
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
