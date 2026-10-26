// End-to-end smoke test: real server + real browser, fake Whisper (no model download).
// Run:  VIDCUT_PYTHON=python node tests/e2e/smoke.mjs   (NODE_PATH must reach a global playwright)
import { spawnSync } from "node:child_process";
import { mkdtempSync, existsSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { chromium, makeWebm, must, startApp } from "./harness.mjs";

const EDITED = "ทดสอบข้อความที่แก้ไข 123";

const clipDir = mkdtempSync(join(tmpdir(), "vidcut-clip-"));
const clip = join(clipDir, "demo.webm");
makeWebm(clip, 30, "sin(2*PI*440*t)*(lt(mod(t\\,5)\\,3))"); // 3 s of tone, 2 s of silence, repeated
const app = await startApp({ VIDCUT_PICK_OVERRIDE: clip, VIDCUT_FAKE_WHISPER: "1" });

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
  await page.click("text=+ เพิ่มคลิป");
  await page.waitForSelector(".clip-list li");
  must(true, "clip added through the file-picker endpoint");

  await page.click("text=ตรวจหาและตัด Dead air");
  await page.waitForSelector(".toast:not(.error)", { timeout: 30000 });
  await page.waitForTimeout(500);
  must(true, "dead air detected");

  const tl = await (await page.$("#edit-timeline-wrap canvas")).boundingBox();
  await page.mouse.click(tl.x + tl.width * 0.05, tl.y + 60); await page.click("text=ตั้ง In");
  await page.mouse.click(tl.x + tl.width * 0.6, tl.y + 60); await page.click("text=ตั้ง Out");
  await page.waitForTimeout(500);
  must(/ช่วงที่เลือก/.test(await page.$eval(".sel-info", (e) => e.textContent)), "selection set");

  await page.click("text=สร้างซับอัตโนมัติ");
  await page.waitForSelector(".sub-row", { timeout: 30000 });
  must((await page.$$(".sub-row")).length >= 1, "subtitles generated");

  const ta = page.locator(".sub-row textarea").first();
  await ta.click(); await ta.fill(EDITED);
  await page.waitForTimeout(600);
  must((await ta.inputValue()) === EDITED, "edited subtitle text is shown in the list");

  await page.click("text=ส่งออกวิดีโอ");
  await page.waitForSelector(".export-result a", { timeout: 120000 });
  const exports = join(app.home, "exports");
  const mp4 = join(exports, "demo_tiktok.mp4"), srt = join(exports, "demo_tiktok.srt");
  must(existsSync(mp4) && existsSync(srt), "export produced .mp4 and .srt");
  const probe = spawnSync("ffprobe", ["-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height", "-of", "csv=p=0", mp4], { encoding: "utf-8" });
  must(probe.stdout.trim() === "1080,1920", "TikTok export is 1080x1920");
  must(readFileSync(srt, "utf-8").includes(EDITED), "the .srt contains the edited text");
  await page.click("text=ล้างไฟล์ชั่วคราว");
  await page.waitForSelector(".toast:not(.error):has-text('ล้างไฟล์ชั่วคราวแล้ว')", { timeout: 10000 });
  must(true, "temp files can be cleared from the UI");
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
