// End-to-end smoke test: real server + real browser, fake Whisper (no model download).
// Run:  NODE_PATH=$(npm root -g) VIDCUT_PYTHON=python node tests/e2e/smoke.mjs
import { createRequire } from "node:module";
import { spawn, spawnSync } from "node:child_process";
import { mkdtempSync, existsSync, readFileSync, rmSync } from "node:fs";
import { createServer } from "node:net";
import { tmpdir } from "node:os";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url); // honours NODE_PATH, unlike ESM import
const { chromium } = require("playwright");
const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
const EDITED = "ทดสอบข้อความที่แก้ไข 123";

const freePort = () => new Promise((res) => { const s = createServer().listen(0, () => { const p = s.address().port; s.close(() => res(p)); }); });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const must = (cond, msg) => { if (!cond) throw new Error("ASSERT: " + msg); console.log("ok  -", msg); };

const work = mkdtempSync(join(tmpdir(), "vidcut-e2e-"));
const clip = join(work, "demo.webm");
const gen = spawnSync("ffmpeg", ["-y", "-hide_banner", "-loglevel", "error",
  "-f", "lavfi", "-i", "testsrc=size=640x360:rate=25:duration=30",
  "-f", "lavfi", "-i", "aevalsrc=sin(2*PI*440*t)*(lt(mod(t\\,5)\\,3)):s=48000:d=30",
  "-c:v", "libvpx", "-b:v", "300k", "-c:a", "libopus", "-shortest", clip]);
if (gen.status !== 0) throw new Error("could not generate the test clip: " + gen.stderr);

const port = await freePort();
const home = join(work, "home");
const server = spawn(process.env.VIDCUT_PYTHON || "python", ["-m", "server.app"], {
  cwd: ROOT, stdio: ["ignore", "pipe", "pipe"],
  env: { ...process.env, VIDCUT_HOME: home, VIDCUT_PORT: String(port), VIDCUT_NO_BROWSER: "1",
         VIDCUT_PICK_OVERRIDE: clip, VIDCUT_FAKE_WHISPER: "1" },
});
let serverLog = "";
server.stderr.on("data", (d) => (serverLog += d));

let failed = false;
let browser;
try {
  for (let i = 0; i < 50; i++) {
    try { if ((await fetch(`http://127.0.0.1:${port}/api/project`)).ok) break; } catch { /* not up yet */ }
    await sleep(200);
  }
  browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  const problems = [];
  page.on("console", (m) => m.type() === "error" && problems.push(m.text()));
  page.on("pageerror", (e) => problems.push(e.message));
  page.on("dialog", (d) => d.accept());

  await page.goto(`http://127.0.0.1:${port}/`);
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
  const exports = join(home, "exports");
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
  if (serverLog) console.error("server log:\n" + serverLog.slice(-1500));
} finally {
  await browser?.close();
  server.kill();
  rmSync(work, { recursive: true, force: true });
}
process.exit(failed ? 1 : 0);
