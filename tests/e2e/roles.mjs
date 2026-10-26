// An intro clip: off the edit timeline (so In/Out stays on the main clip), joined in front at export.
import { spawnSync } from "node:child_process";
import { existsSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { chromium, makeWebm, startApp, must, sleep } from "./harness.mjs";

const app = await startApp();
let browser, failed = false;
try {
  const main = join(app.work, "main.webm"), intro = join(app.work, "intro.webm");
  makeWebm(main, 4); makeWebm(intro, 2);
  for (const path of [main, intro]) {
    const r = await fetch(`${app.base}/api/clips`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ path }) });
    if (!r.ok) throw new Error("add clip failed: " + (await r.text()));
  }
  browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  const problems = [];
  page.on("console", (m) => m.type() === "error" && problems.push(m.text()));
  page.on("pageerror", (e) => problems.push(e.message));
  await page.goto(app.base);
  await page.waitForSelector(".clip-list li:nth-child(2)");
  await sleep(800);
  must(/\/ 0:06\.\d/.test(await page.$eval(".clock", (e) => e.textContent)), "both clips are on the timeline at first (6 s)");

  await page.selectOption(".clip-list li:nth-child(2) select.role", "intro");
  await sleep(600);
  must(/\/ 0:04\.\d/.test(await page.$eval(".clock", (e) => e.textContent)), "after making it an intro the timeline is only the main clip (4 s)");

  await page.keyboard.press("i"); // selection from the playhead (0) to the end of the main timeline
  await sleep(500);
  await page.click("text=Export video");
  await page.waitForSelector(".export-result a", { timeout: 120000 });
  const dir = join(app.home, "exports");
  const file = readdirSync(dir).find((f) => f.endsWith(".mp4"));
  must(file, "export produced an mp4");
  const dur = parseFloat(spawnSync("ffprobe", ["-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", join(dir, file)], { encoding: "utf-8" }).stdout);
  must(Math.abs(dur - 6) < 0.2, `exported file is intro + main = 6 s (got ${dur.toFixed(2)})`);
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
