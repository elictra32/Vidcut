// End-to-end smoke test: real server + real browser, fake Whisper (no model download).
// Run:  VIDCUT_PYTHON=python node tests/e2e/smoke.mjs   (NODE_PATH must reach a global playwright)
import { spawnSync } from "node:child_process";
import { mkdtempSync, existsSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { chromium, makeWebm, must, startApp } from "./harness.mjs";

const EDITED = "ทดสอบข้อความที่แก้ไข 123";

const clipDir = mkdtempSync(join(tmpdir(), "vidcut-clip-"));
const clip = join(clipDir, "demo.webm");
makeWebm(clip, 30, "sin(2*PI*440*t)*(lt(mod(t\\,5)\\,3))"); // 3 s of tone, 2 s of silence, repeated
const pickedDir = join(clipDir, "picked-folder");
const app = await startApp({ VIDCUT_PICK_OVERRIDE: clip, VIDCUT_FAKE_WHISPER: "1", VIDCUT_PICK_FOLDER_OVERRIDE: pickedDir });

let failed = false;
let browser;
try {
  browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  const problems = [];
  page.on("console", (m) => m.type() === "error" && problems.push(m.text()));
  page.on("pageerror", (e) => problems.push(e.message));
  page.on("dialog", (d) => d.accept());

  await page.goto(app.base);
  await page.click("text=+ Add clip");
  await page.waitForSelector(".clip-list li");
  must(true, "clip added through the file-picker endpoint");

  await page.click("text=Detect and cut dead air");
  await page.waitForSelector(".toast:not(.error)", { timeout: 30000 });
  await page.waitForTimeout(500);
  must(true, "dead air detected");

  const tl = await (await page.$("#edit-timeline-wrap canvas")).boundingBox();
  await page.mouse.click(tl.x + tl.width * 0.05, tl.y + 60); await page.click("text=Set In");
  await page.mouse.click(tl.x + tl.width * 0.6, tl.y + 60); await page.click("text=Set Out");
  await page.waitForTimeout(500);
  must(/Selection/.test(await page.$eval(".sel-info", (e) => e.textContent)), "selection set");

  await page.click("text=Generate subtitles");
  await page.waitForSelector(".sub-row", { timeout: 30000 });
  must((await page.$$(".sub-row")).length >= 1, "subtitles generated");

  const ta = page.locator(".sub-row textarea").first();
  await ta.click(); await ta.fill(EDITED);
  await page.waitForTimeout(600);
  must((await ta.inputValue()) === EDITED, "edited subtitle text is shown in the list");

  await page.click("text=Export video");
  await page.waitForSelector(".export-result a", { timeout: 120000 });
  const exports = join(app.home, "exports");
  const mp4 = join(exports, "demo_tiktok.mp4"), srt = join(exports, "demo_tiktok.srt");
  must(existsSync(mp4) && existsSync(srt), "export produced .mp4 and .srt");
  const probe = spawnSync("ffprobe", ["-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height", "-of", "csv=p=0", mp4], { encoding: "utf-8" });
  must(probe.stdout.trim() === "1080,1920", "TikTok export is 1080x1920");
  must(readFileSync(srt, "utf-8").includes(EDITED), "the .srt contains the edited text");
  await page.click("text=Clear temp files");
  await page.waitForSelector(".toast:not(.error):has-text('Temporary files cleared')", { timeout: 10000 });
  must(true, "temp files can be cleared from the UI");
  // import an SRT (UTF-8 with BOM and CRLF, as YouTube Studio writes it): text kept, tags and fillers removed
  const srtPath = join(clipDir, "captions.srt");
  writeFileSync(srtPath, "\ufeff1\r\n00:00:01,000 --> 00:00:04,000\r\nทดสอบนำเข้าซับจากยูทูป\r\n\r\n" +
    "2\r\n00:00:04,500 --> 00:00:08,000\r\nเออ\r\n\r\n3\r\n00:00:08,000 --> 00:00:12,000\r\n[เสียงหัวเราะ]ข้อความที่สอง\r\n", "utf-8");
  await page.setInputFiles("#srt-file", srtPath);
  await page.waitForSelector("dialog[open]");
  const offsetHelp = await page.$eval("dialog[open]", (d) => d.textContent);
  must(/positive = subtitles appear later/.test(offsetHelp) && /negative = earlier/.test(offsetHelp), "the time-shift field says which direction a positive/negative value moves the subtitles");
  const onlySelection = page.locator("dialog[open] input[type=checkbox]");
  if (await onlySelection.isChecked()) await onlySelection.uncheck();
  await page.click("dialog[open] button.primary"); // replaces the existing subtitles; the confirm() is auto-accepted
  await page.waitForSelector(".toast:not(.error):has-text('Imported')", { timeout: 10000 });
  const imported = (await page.$$eval(".sub-row textarea", (n) => n.map((x) => x.value))).join("").replaceAll("\n", ""); // long lines wrap into rows
  must(imported.includes("ทดสอบนำเข้าซับจากยูทูป") && imported.includes("ข้อความที่สอง"), "SRT import: the cue text is in the subtitle list");
  must(!imported.includes("เสียงหัวเราะ") && !imported.includes("เออ"), "SRT import: tags and fillers were removed");
  // export options: another format and size, a size estimate, and a chosen folder
  await page.selectOption("#opt-container", "mkv");
  await page.selectOption("#opt-quality", "small");
  await page.waitForFunction(() => /MB/.test(document.querySelector("#estimate")?.textContent ?? ""), null, { timeout: 10000 });
  must(/approx\. size/.test(await page.$eval("#estimate", (e) => e.textContent)), "the export panel shows a size estimate");
  await page.click("#opt-folder-pick");
  await page.waitForFunction(() => document.querySelector(".folder-text")?.textContent.includes("picked-folder"), null, { timeout: 10000 });
  await page.click("text=Export video");
  await page.waitForSelector(".export-result:has-text('picked-folder')", { timeout: 120000 });
  must(existsSync(join(pickedDir, "demo_tiktok.mkv")) && existsSync(join(pickedDir, "demo_tiktok.srt")), "the MKV and .srt were written to the chosen folder");
  must(problems.length === 0, "no console errors" + (problems.length ? ": " + problems.join(" | ") : ""));
} catch (e) {
  failed = true;
  console.error("FAIL:", e.message);
  if (app.log()) console.error("server log:\n" + app.log().slice(-1500));
} finally {
  await browser?.close();
  app.stop();
  rmSync(clipDir, { recursive: true, force: true });
}
process.exit(failed ? 1 : 0);
