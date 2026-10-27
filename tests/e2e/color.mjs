// Colour correction: a preset and a slider change the clip's grade, the preview shows it, it is saved, and undo undoes it.
import { join } from "node:path";
import { chromium, makeWebm, startApp, must, sleep } from "./harness.mjs";

const app = await startApp();
let browser, failed = false;
try {
  const clip = join(app.work, "a.webm");
  makeWebm(clip, 6);
  await fetch(`${app.base}/api/clips`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ path: clip }) });
  browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  const problems = [];
  page.on("console", (m) => m.type() === "error" && problems.push(m.text()));
  page.on("pageerror", (e) => problems.push(e.message));
  await page.goto(app.base);
  await page.waitForSelector('#color-panel [data-preset="Less yellow"]');
  const saved = async () => (await (await fetch(`${app.base}/api/project`)).json()).project.clips[0].grade;
  const filter = () => page.$eval("#video", (v) => v.style.filter);
  must((await filter()) === "", "an untouched clip has no colour filter");
  await page.click('#color-panel [data-preset="Less yellow"]');
  await sleep(900);
  must((await saved()).temperature === -35, "the Less yellow preset is saved on the clip");
  must(/grade-video/.test(await filter()), "the preview video gets the colour filter");
  const m = await page.$eval("#grade-video feColorMatrix", (e) => e.getAttribute("values").split(" ").map(Number));
  must(m[0] < 1 && m[12] > 1, "the filter takes red down and blue up");
  const num = page.locator("#color-panel .numslider input.num").nth(2);   // Brightness
  await num.fill("20"); await num.press("Tab");
  await sleep(900);
  must((await saved()).brightness === 20, "typing a number in a slider box sets it");
  await page.click("#btn-undo");
  await sleep(1200);
  must((await saved()).brightness === 0 && (await saved()).temperature === -35, "undo takes back the last slider change only");
  await page.click("#btn-grade-reset");
  await sleep(900);
  must((await filter()) === "" && (await saved()).temperature === 0, "Reset returns to the original colours");
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
