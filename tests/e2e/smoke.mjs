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
  page.on("response", (r) => r.status() >= 400 && problems.push(`${r.status()} ${r.request().method()} ${new URL(r.url()).pathname}`)); // which request failed
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

  // confirming the cuts tucks the review strip away; it can be reopened
  must(await page.isVisible("#cut-strip-wrap canvas"), "the review strip is shown before confirming");
  await page.click("#btn-confirm-cuts");
  must(!(await page.isVisible("#cut-strip-wrap canvas")) && await page.isVisible("#btn-edit-cuts"), "Confirm cuts hides the review strip");
  await page.click("#btn-edit-cuts");
  must(await page.isVisible("#cut-strip-wrap canvas"), "Edit cuts brings the review strip back");
  await page.click("#btn-confirm-cuts");

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

  // per-line tools: character count, size, split and merge
  must(/^\d+ chars$/.test(await page.locator(".sub-row .chars").first().textContent()), "each line shows its character count");
  const before = (await page.$$(".sub-row")).length;
  await page.locator(".sub-row textarea").first().evaluate((t) => t.setSelectionRange(3, 3));
  await page.locator(".sub-row >> text=Split").first().click();
  await page.waitForFunction((n) => document.querySelectorAll(".sub-row").length === n + 1, before, { timeout: 5000 });
  must(true, "Split breaks a line in two");
  await page.locator(".sub-row >> text=Merge").first().click();
  await page.waitForFunction((n) => document.querySelectorAll(".sub-row").length === n, before, { timeout: 5000 });
  must(true, "Merge joins a line with the next one");
  const sizeInput = page.locator(".sub-row .numslider input[type=range]").first();
  await page.locator(".sub-row .numslider .num").first().fill("150");
  await page.locator(".sub-row .numslider .num").first().press("Tab"); // typing an exact number also works
  await page.waitForTimeout(700);
  must(await page.evaluate(async () => (await (await fetch("/api/project")).json()).project.subtitles.some((x) => x.scale === 1.5)), "typing 150 in the size box sets the line size to 150%");
  await sizeInput.evaluate((i) => { i.value = 2; i.dispatchEvent(new Event("input")); });
  must(await page.locator(".sub-row .numslider .num").first().inputValue() === "200", "the number box follows the slider");
  await page.waitForTimeout(700);
  must(await page.evaluate(async () => (await (await fetch("/api/project")).json()).project.subtitles.some((x) => x.scale === 2)), "per-line size is saved");
  await page.locator(".sub-row textarea").first().fill(EDITED);

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
  must(!(await page.isVisible("#opt-target")), "the target-size box is hidden unless quality is Custom size");
  await page.selectOption("#opt-quality", "custom");
  must(await page.isVisible("#opt-target"), "the target-size box shows for Custom size");
  await page.selectOption("#opt-quality", "small");
  await page.waitForFunction(() => /approx\. size.*MB/.test(document.querySelector("#estimate")?.textContent ?? ""), null, { timeout: 10000 });
  must(/approx\. size/.test(await page.$eval("#estimate", (e) => e.textContent)), "the export panel shows a size estimate");
  await page.click("#opt-folder-pick");
  await page.waitForFunction(() => document.querySelector(".folder-text")?.textContent.includes("picked-folder"), null, { timeout: 10000 });
  await page.click("text=Export video");
  await page.waitForSelector(".export-result:has-text('picked-folder')", { timeout: 120000 });
  must(existsSync(join(pickedDir, "demo_tiktok.mkv")) && existsSync(join(pickedDir, "demo_tiktok.srt")), "the MKV and .srt were written to the chosen folder");
  // reveal: the preview shows only the spoken part of a line, and the rest keeps its place
  await page.check("#opt-reveal");
  await page.evaluate(async () => {
    const st = await import("/state.js");
    const sub = st.getProject().subtitles[0];
    const tm = await import("/timeline_math.js");
    const span = tm.subtitleEditedSpan(st.getProject().clips, sub);
    await (await import("/player.js")).seek(span[0] + 0.01);
  });
  await page.waitForFunction(() => document.querySelector("#sub-overlay .sub span"), null, { timeout: 5000 });
  const parts = await page.$eval("#sub-overlay .sub", (n) => ({ shown: n.firstChild.textContent, hidden: n.querySelector("span").textContent, vis: getComputedStyle(n.querySelector("span")).visibility }));
  must(parts.vis === "hidden" && parts.hidden.length > 0 && parts.shown.length > 0, `reveal shows the start of the line and hides the rest (${parts.shown}|${parts.hidden})`);
  await page.uncheck("#opt-reveal");

  // delete every subtitle at once
  await page.click("#btn-delete-all-subs");
  await page.waitForSelector(".sub-list .sub-row", { state: "detached", timeout: 5000 });
  must((await page.$$(".sub-list .sub-row")).length === 0, "Delete all removes every subtitle");
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
