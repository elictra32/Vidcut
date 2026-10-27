// Captions made for the ORIGINAL video, imported onto its cut version through a Vidcut cut file.
import { writeFileSync } from "node:fs";
import { join } from "node:path";
import { chromium, makeWebm, startApp, must } from "./harness.mjs";

const app = await startApp();
let browser, failed = false;
try {
  const clip = join(app.work, "cutversion.webm");
  makeWebm(clip, 20);
  await fetch(`${app.base}/api/clips`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ path: clip }) });
  writeFileSync(join(app.work, "cutversion.vidcut.json"), JSON.stringify({ version: 1, video: "cutversion.webm", sources: [
    { name: "original.mp4", role: "main", pieces: [{ src_start: 100, src_end: 110, out_start: 0 }, { src_start: 120, src_end: 130, out_start: 10 }] }] }));
  browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  const problems = [];
  page.on("console", (m) => m.type() === "error" && problems.push(m.text()));
  page.on("pageerror", (e) => problems.push(e.message));
  await page.goto(app.base);
  await page.waitForSelector("#srt-file", { state: "attached" });
  const srt = "1\n00:01:40,500 --> 00:01:43,000\nสวัสดีครับทุกคน\n\n2\n00:03:00,000 --> 00:03:02,000\nช่วงที่ถูกตัดออก\n\n3\n00:02:00,000 --> 00:02:03,000\nวันนี้เรามาตัดต่อ\n";
  await page.setInputFiles("#srt-file", { name: "orig.srt", mimeType: "text/plain", buffer: Buffer.from(srt, "utf-8") });
  await page.waitForSelector("dialog[open]");
  await page.uncheck("dialog[open] input[type=checkbox]").catch(() => {});
  await page.selectOption("#srt-mode", "cut");
  await page.waitForFunction(() => /Found the Vidcut cut file/.test(document.querySelector("#srt-cut-status")?.textContent ?? ""), null, { timeout: 5000 });
  must(!(await page.isVisible("#btn-pick-original")), "a cut file next to the video is used automatically");
  await page.click("dialog[open] button.primary");
  await page.waitForSelector(".toast:not(.error):has-text('Imported')", { timeout: 10000 });
  const text = await page.$$eval(".sub-row textarea", (els) => els.map((e) => e.value).join(""));
  must(text.includes("สวัสดีครับทุกคน") && text.includes("วันนี้เรามาตัดต่อ"), "captions of the kept parts were imported");
  must(!text.includes("ถูกตัดออก"), "a caption from a removed part was dropped");
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
