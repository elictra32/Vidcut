// Highlight reel: "Find short shots" lists every scolding moment, unticking drops one, "Make reel" leaves only the
// ticked shots on the timeline; the timeline has a scrollbar that pans it; Ctrl+Z brings everything back.
import { join } from "node:path";
import { chromium, makeWebm, startApp, must } from "./harness.mjs";

const app = await startApp();
let browser, failed = false;
try {
  const clip = join(app.work, "a.webm");
  makeWebm(clip, 90);
  const json = { "Content-Type": "application/json" };
  const added = await (await fetch(`${app.base}/api/clips`, { method: "POST", headers: json, body: JSON.stringify({ path: clip }) })).json();
  const p = (await (await fetch(`${app.base}/api/project`)).json()).project;
  const scold = new Set([3, 12, 21, 27]);   // four scolding moments, 3 s lines
  p.subtitles = Array.from({ length: 30 }, (_, i) => ({ id: `s${i}`, clip_id: added.clip.id, src_start: i * 3, src_end: i * 3 + 2.5,
    text: scold.has(i) ? "ไอ้โง่ ไม่ได้เรื่อง" : "วันนี้เรียนเรื่องบัญชี", x: null, y: null }));
  await fetch(`${app.base}/api/project`, { method: "PUT", headers: json, body: JSON.stringify(p) });

  browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  const problems = [];
  page.on("console", (m) => m.type() === "error" && problems.push(m.text()));
  page.on("pageerror", (e) => problems.push(e.message));
  await page.goto(app.base);
  await page.waitForSelector("#btn-scan-shots");
  await page.click("#btn-scan-shots");
  await page.waitForSelector('.hl-row[data-cat="scold"] .hl-pick', { timeout: 15000 });
  must((await page.$$('.hl-row[data-cat="scold"]')).length === 4, "every scolding moment is listed as its own short shot");
  await page.locator('.hl-row[data-cat="scold"] .hl-pick').nth(3).uncheck();
  must((await page.textContent("#btn-make-reel")).includes("3 checked"), "unticking a shot updates the button");
  // the same ticked shots can instead be exported, each as its own file, through the queue
  must((await page.textContent("#btn-export-highlights")).includes("Export 3 checked"), "the export button counts the ticked highlights");
  await page.click("#btn-export-highlights");
  let q;
  for (let i = 0; i < 120; i++) {
    q = await (await fetch(`${app.base}/api/queue`)).json();
    if (q.items.length && ["done", "error"].includes(q.items[0].state)) break;
    await page.waitForTimeout(500);
  }
  must(q.items[0].state === "done" && q.items[0].result.files.length === 3, `3 separate highlight files were exported (${q.items[0].state})`);
  const total0 = await page.evaluate(async () => { const t = await import("/timeline_math.js"); const s = await import("/state.js"); return t.editedDuration(s.getProject().clips); });
  await page.click("#btn-make-reel");
  await page.waitForTimeout(900);
  const after = await page.evaluate(async () => { const t = await import("/timeline_math.js"); const s = await import("/state.js");
    return { total: t.editedDuration(s.getProject().clips), segs: t.segments(s.getProject().clips).length }; });
  must(after.segs === 3 && after.total < total0 / 3 && after.total > 6, `the timeline holds only the 3 ticked shots (${after.segs} segments, ${after.total.toFixed(1)} s of ${total0.toFixed(0)} s)`);

  // scrollbar: zoom in, then drag the thumb and the view moves
  await page.click('.tl-bar button:has-text("Zoom in")');
  await page.waitForTimeout(200);
  const v0 = await page.evaluate(async () => (await import("/timeline_view.js")).getView().start);
  const tb = await (await page.$(".tl-thumb")).boundingBox();
  await page.mouse.move(tb.x + tb.width / 2, tb.y + tb.height / 2);
  await page.mouse.down();
  await page.mouse.move(tb.x + tb.width / 2 + 200, tb.y + tb.height / 2, { steps: 4 });
  await page.mouse.up();
  const v1 = await page.evaluate(async () => (await import("/timeline_view.js")).getView().start);
  must(v1 > v0, `dragging the scrollbar pans the timeline sideways (${v0.toFixed(1)} → ${v1.toFixed(1)})`);

  await page.keyboard.press("Control+z");
  await page.waitForTimeout(500);
  const back = await page.evaluate(async () => (await import("/timeline_math.js")).editedDuration((await import("/state.js")).getProject().clips));
  must(Math.abs(back - total0) < 0.5, "Ctrl+Z brings the whole clip back");
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
