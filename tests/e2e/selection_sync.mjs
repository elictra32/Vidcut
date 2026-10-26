// The page shows a selection that the server does not have (a save was lost or lagged). Asking for
// subtitles must not fail with "no selection selected": the page re-sends its project and retries.
import { chromium, makeWebm, startApp, must, sleep } from "./harness.mjs";
import { join } from "node:path";

const app = await startApp({ VIDCUT_FAKE_WHISPER: "1" });
let browser, failed = false;
try {
  const clip = join(app.work, "a.webm");
  makeWebm(clip, 12);
  const json = { "Content-Type": "application/json" };
  await fetch(`${app.base}/api/clips`, { method: "POST", headers: json, body: JSON.stringify({ path: clip }) });
  browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  const problems = [];
  // the first transcribe request is expected to be answered with a 400 (that is what triggers the retry)
  page.on("console", (m) => m.type() === "error" && !/status of 400/.test(m.text()) && problems.push(m.text()));
  page.on("pageerror", (e) => problems.push(e.message));
  page.on("dialog", (d) => d.accept());
  await page.goto(app.base);
  await page.waitForSelector(".clip-list li");
  await sleep(800);

  await page.evaluate(async () => (await import("/state.js")).update((p) => (p.selection = { start: 1, end: 6 }), "selection"));
  await sleep(1200); // the page has saved it
  // sabotage: the server forgets the selection although the page believes it saved it
  const server = await (await fetch(`${app.base}/api/project`)).json();
  server.project.selection = null;
  const put = await fetch(`${app.base}/api/project`, { method: "PUT", headers: json, body: JSON.stringify(server.project) });
  must(put.ok, "set up: the server no longer has the selection");
  must(/ช่วงที่เลือก/.test(await page.$eval(".sel-info", (e) => e.textContent)), "set up: the page still shows its selection");

  await page.click("text=สร้างซับอัตโนมัติ");
  await page.waitForSelector(".sub-row", { timeout: 20000 });
  must(true, "subtitles were generated anyway (the page re-sent the selection and retried)");
  const toasts = await page.$$eval(".toast.error", (n) => n.map((x) => x.textContent));
  must(toasts.length === 0, "no error toast was shown" + (toasts.length ? `: ${toasts.join(" | ")}` : ""));
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
