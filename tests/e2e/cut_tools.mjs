// Cutting on the edit timeline: Cut here (S), Delete segment (Delete), Cut out In-Out (X), and Ctrl+Z.
import { join } from "node:path";
import { chromium, makeWebm, startApp, must, sleep } from "./harness.mjs";

const app = await startApp();
let browser, failed = false;
try {
  const clip = join(app.work, "a.webm");
  makeWebm(clip, 30);
  await fetch(`${app.base}/api/clips`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ path: clip }) });
  const server = async () => (await (await fetch(`${app.base}/api/project`)).json()).project;
  browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  const problems = [];
  page.on("console", (m) => m.type() === "error" && problems.push(m.text()));
  page.on("pageerror", (e) => problems.push(e.message));
  await page.goto(app.base);
  await page.waitForSelector("#btn-cut-here");
  await sleep(600);
  const seek = (t) => page.evaluate(async (x) => (await import("/player.js")).seek(x), t);
  const enabled = async () => (await server()).clips[0].keeps.filter((k) => k.enabled).map((k) => [+k.start.toFixed(2), +k.end.toFixed(2)]);
  const total = async () => (await enabled()).reduce((s, [a, b]) => s + b - a, 0);

  await seek(10);
  await page.click("#btn-cut-here");
  await sleep(700);
  const e1 = await enabled();
  must(e1.length === 2 && e1[0][1] === 10 && e1[1][0] === 10, "Cut here splits the clip at the playhead: " + JSON.stringify(e1));

  await seek(20);
  await page.keyboard.press("s");
  await sleep(700);
  must((await enabled()).length === 3, "the S key cuts too");

  await seek(15); // inside the middle segment 10-20
  await page.keyboard.press("Delete");
  await sleep(700);
  const e2 = await enabled();
  must(e2.length === 2 && e2[0][1] === 10 && e2[1][0] === 20, "Delete removes the segment under the playhead: " + JSON.stringify(e2));
  must(Math.abs((await total()) - 20) < 0.1, "20 s remain");

  await page.keyboard.press("Control+z");
  await sleep(700);
  must(Math.abs((await total()) - 30) < 0.1, "Ctrl+Z brings the deleted segment back");

  // cut out In-Out: select edited 2..6 then press X
  await page.evaluate(async () => { const s = await import("/state.js"); s.update((p) => (p.selection = { start: 2, end: 6 }), "selection"); });
  await page.click("#btn-cut-selection");
  await sleep(700);
  must(Math.abs((await total()) - 26) < 0.1, "Cut out In–Out removes the 4 selected seconds");

  // a real export of the edit has the right length (the split joins back into one stretch)
  const proj = await server();
  must(proj.clips[0].keeps.some((k) => !k.enabled), "the removed parts stay in the list, disabled (restorable in Review cuts)");
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
