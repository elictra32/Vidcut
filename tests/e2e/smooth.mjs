// Playing across removed gaps must not freeze the picture. Records every frame the browser presents
// (requestVideoFrameCallback on every <video>) and reports the longest wall-clock gap between frames.
// Uses a 1080p clip with a long keyframe interval, where a seek is expensive (like phone footage).
import { chromium, makeWebm, startApp, must, sleep } from "./harness.mjs";
import { join } from "node:path";

const MARGIN_MS = Number(process.env.MARGIN_MS || 80); // allowed extra over the no-cut worst gap
const app = await startApp();
let browser, failed = false;
try {
  const clip = join(app.work, "talk.webm");
  // 3 s of tone, 2 s of silence, repeated: every 5 s there is a removed gap
  makeWebm(clip, 26, "sin(2*PI*440*t)*(lt(mod(t\\,5)\\,3))", { size: "1920x1080", gop: 250, kbps: 2500 });
  const add = await (await fetch(`${app.base}/api/clips`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ path: clip }) })).json();

  browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  const problems = [];
  page.on("console", (m) => m.type() === "error" && problems.push(m.text()));
  page.on("pageerror", (e) => problems.push(e.message));
  await page.goto(app.base);
  await page.waitForSelector(".clip-list li");
  await sleep(1000);

  // Records every presented frame (requestVideoFrameCallback on each <video>) while playing from 0 for `ms`.
  const measure = async (ms) => {
    await page.evaluate(() => {
      window.__frames = [];
      document.querySelectorAll("#frame video").forEach((v) => {
        if (v.__watched) return;
        v.__watched = true;
        const cb = (now) => { window.__frames.push(now); v.requestVideoFrameCallback(cb); };
        v.requestVideoFrameCallback(cb);
      });
    });
    await page.evaluate(async () => { const pl = await import("/player.js"); await pl.seek(0); await pl.play(); });
    await sleep(ms);
    await page.evaluate(async () => (await import("/player.js")).pause());
    const frames = await page.evaluate(() => window.__frames);
    return { frames: frames.length, gaps: frames.slice(1).map((t, i) => t - frames[i]).sort((a, b) => b - a) };
  };

  // Control: the whole clip, no cuts. Its worst gap is this machine's own decode/render jitter.
  const control = await measure(9000);
  console.log(`control (no cuts): frames=${control.frames}; worst gaps (ms):`, control.gaps.slice(0, 4).map(Math.round).join(", "));

  // Now remove the silences and play across three of the gaps.
  const job = (await (await fetch(`${app.base}/api/clips/${add.clip.id}/silence`, { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" })).json()).job;
  for (let i = 0; i < 100; i++) { const j = await (await fetch(`${app.base}/api/jobs/${job}`)).json(); if (j.state === "done") break; await sleep(200); }
  await page.reload();
  await page.waitForSelector(".clip-list li");
  await sleep(1000);
  const keeps = await page.evaluate(async () => (await import("/state.js")).getProject().clips[0].keeps.length);
  const cut = await measure(17000);
  console.log(`with ${keeps - 1} cuts: frames=${cut.frames}; worst gaps (ms):`, cut.gaps.slice(0, 5).map(Math.round).join(", "));

  must(keeps >= 5, `dead air was removed (${keeps} kept segments)`);
  must(cut.frames > 150, `playback across the cuts produced frames (${cut.frames})`);
  must(cut.gaps[0] <= control.gaps[0] + MARGIN_MS, `cuts add no freeze beyond the machine's own jitter (worst ${Math.round(cut.gaps[0])} ms vs ${Math.round(control.gaps[0])} ms without cuts, margin ${MARGIN_MS} ms)`);
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
