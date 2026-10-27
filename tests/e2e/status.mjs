// Several jobs at once: each gets its own row in the header, one finishing does not hide the other, and the queue shows its
// running item there too (so it never looks idle while it works).
import { join } from "node:path";
import { chromium, makeWebm, startApp, must, sleep } from "./harness.mjs";

const app = await startApp();
let browser, failed = false;
try {
  const j = { "Content-Type": "application/json" };
  makeWebm(join(app.work, "a.webm"), 8);
  await fetch(`${app.base}/api/clips`, { method: "POST", headers: j, body: JSON.stringify({ path: join(app.work, "a.webm") }) });
  browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  const problems = [];
  page.on("console", (m) => m.type() === "error" && problems.push(m.text()));
  page.on("pageerror", (e) => problems.push(e.message));
  await page.goto(app.base);
  await page.waitForSelector(".clip-list li");
  const job = async (title) => (await (await fetch(`${app.base}/api/covers`, { method: "POST", headers: j, body: JSON.stringify({ format: "vertical", items: [{ title }], date_text: "x", replace_intros: false }) })).json()).job;
  const [a, b] = [await job("Alpha"), await job("Beta")];
  await page.evaluate(async ([a, b]) => {
    const s = await import("/status.js");
    window.__done = [];
    s.trackJob("Making covers A", a).then(() => window.__done.push("a"));
    s.trackJob("Making covers B", b).then(() => window.__done.push("b"));
  }, [a, b]);
  await sleep(300);
  must((await page.$$("#status .status-job[data-kind=job]")).length === 2, "two running jobs are two rows in the header");
  await page.waitForFunction(() => window.__done.length === 1, null, { timeout: 120000 });
  const left = (await page.$$("#status .status-job[data-kind=job]")).length;
  const hidden = await page.$eval("#status", (e) => e.hidden);
  must(left === 1 && !hidden || window.__done === 2, "when one job finishes the other one stays visible");
  await page.waitForFunction(() => window.__done.length === 2, null, { timeout: 120000 });
  must(await page.$eval("#status", (e) => e.hidden), "the area hides when nothing is running");
  // the queue
  await fetch(`${app.base}/api/queue/pause`, { method: "POST" });
  await fetch(`${app.base}/api/queue`, { method: "POST", headers: j, body: JSON.stringify({ kind: "export" }) });
  await page.waitForSelector("#status .status-job[data-kind=queue]", { timeout: 8000 });
  must(/paused/i.test(await page.textContent("#status .status-job[data-kind=queue]")), "a paused queue with a waiting item says so in the header");
  await fetch(`${app.base}/api/queue/resume`, { method: "POST" });
  await page.waitForSelector(".toast:has-text('Finished')", { timeout: 120000 });
  must(true, "a finished queue item is announced with a toast");
  await page.waitForFunction(() => document.querySelector("#status").hidden, null, { timeout: 15000 });
  must(true, "the header goes quiet when the queue is empty");
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
