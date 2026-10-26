// The subtitle preview must be painted ABOVE the video, not merely present in the DOM.
import { chromium, makeWebm, startApp, must, sleep } from "./harness.mjs";
import { join } from "node:path";

const app = await startApp({ VIDCUT_FAKE_WHISPER: "1" });
let browser, failed = false;
try {
  const clip = join(app.work, "a.webm");
  makeWebm(clip, 10);
  const json = { "Content-Type": "application/json" };
  const added = await (await fetch(`${app.base}/api/clips`, { method: "POST", headers: json, body: JSON.stringify({ path: clip }) })).json();
  const p = (await (await fetch(`${app.base}/api/project`)).json()).project;
  p.subtitles = [{ id: "s1", clip_id: added.clip.id, src_start: 1.0, src_end: 4.0, text: "ทดสอบซับบนภาพ", x: null, y: null }];
  await fetch(`${app.base}/api/project`, { method: "PUT", headers: json, body: JSON.stringify(p) });

  browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  const problems = [];
  page.on("console", (m) => m.type() === "error" && problems.push(m.text()));
  page.on("pageerror", (e) => problems.push(e.message));
  await page.goto(app.base);
  await page.waitForSelector(".sub-row");
  await sleep(800);
  await page.evaluate(async () => (await import("/player.js")).seek(2.0)); // inside the subtitle
  await page.waitForSelector("#sub-overlay .sub", { timeout: 5000 });
  const top = await page.evaluate(() => {
    const sub = document.querySelector("#sub-overlay .sub");
    const r = sub.getBoundingClientRect();
    const hit = document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2);
    return { found: !!sub, isSub: !!hit && (hit === sub || sub.contains(hit)), hit: hit ? `${hit.tagName}#${hit.id}.${hit.className}` : null };
  });
  must(top.found, "the subtitle is in the preview overlay");
  must(top.isSub, `the subtitle is painted above the video (topmost element there: ${top.hit})`);
  await page.screenshot({ path: process.env.SHOT || "/tmp/overlay.png" });
  must(problems.length === 0, "no console errors");
} catch (e) {
  failed = true;
  console.error("FAIL:", e.message);
  if (app.log()) console.error("server log:\n" + app.log().slice(-1500));
} finally {
  await browser?.close();
  app.stop();
}
process.exit(failed ? 1 : 0);
