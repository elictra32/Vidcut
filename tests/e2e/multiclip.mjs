// Playback must continue from one clip into the next, also when a clip's last kept moment is the end of its file.
import { chromium, makeWebm, startApp, must, sleep } from "./harness.mjs";
import { join } from "node:path";

/** Poll an async page check (waitForFunction treats a returned Promise as already true). */
async function until(check, timeoutMs) {
  const end = Date.now() + timeoutMs;
  while (Date.now() < end) { if (await check()) return true; await sleep(100); }
  return false;
}

const app = await startApp();
let browser, failed = false;
try {
  const a = join(app.work, "a.webm"), b = join(app.work, "b.webm");
  makeWebm(a, 4); makeWebm(b, 4);
  for (const path of [a, b]) {
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

  const ids = await page.evaluate(async () => (await import("/state.js")).getProject().clips.map((c) => c.id));
  // Race-free: silence the animation-frame loop so only the video's 'ended' event can carry playback on.
  // (With the loop running, whether it or 'ended' notices the end first is timing luck.)
  await page.evaluate(async () => {
    const pl = await import("/player.js");
    await pl.seek(3.4);
    window.requestAnimationFrame = () => 0;
    await pl.play();
  });
  const player = (fn, arg) => page.evaluate(async ([src, a]) => { const pl = await import("/player.js"); return new Function("pl", "a", src)(pl, a); }, [fn, arg]);
  await until(() => player("return pl.getLoadedClipId() === a", ids[1]), 8000);
  must(await player("return pl.getLoadedClipId() === a", ids[1]), "playback moved on into the second clip");
  await until(() => player("return !pl.isPlaying()"), 12000);
  const end = await player("return { playing: pl.isPlaying(), t: pl.getTime() }");
  must(!end.playing && Math.abs(end.t - 8) < 0.3, `playback stopped at the end of the project (t=${end.t.toFixed(2)})`);
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
