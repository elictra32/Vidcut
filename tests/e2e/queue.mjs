// The job queue: add exports from the Export panel, pause, reorder, cancel, resume, and see them finish.
import { existsSync } from "node:fs";
import { join } from "node:path";
import { chromium, makeWebm, startApp, must, sleep } from "./harness.mjs";

const app = await startApp();
let browser, failed = false;
try {
  const json = { "Content-Type": "application/json" };
  const clip = join(app.work, "a.webm");
  makeWebm(clip, 6);
  await fetch(`${app.base}/api/clips`, { method: "POST", headers: json, body: JSON.stringify({ path: clip }) });
  const out = join(app.work, "qout");
  await fetch(`${app.base}/api/export-folder`, { method: "POST", headers: json, body: JSON.stringify({ path: out }) });
  const queue = async () => (await (await fetch(`${app.base}/api/queue`)).json());

  browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  const problems = [];
  page.on("console", (m) => m.type() === "error" && problems.push(m.text()));
  page.on("pageerror", (e) => problems.push(e.message));
  page.on("dialog", (d) => d.accept());
  await page.goto(app.base);
  await page.waitForSelector("#btn-queue-export");
  await page.click("#btn-queue-pause");
  await page.waitForFunction(() => document.querySelector("#btn-queue-pause")?.textContent === "Resume queue");
  must((await queue()).paused === true, "Pause queue pauses it on the server");

  // three exports with different selections, so each has its own length
  for (const [a, b] of [[0, 2], [2, 5], [1, 4]]) {
    await page.evaluate(async ([s, e]) => { const st = await import("/state.js"); st.update((p) => (p.selection = { start: s, end: e }), "selection"); }, [a, b]);
    await page.click("#btn-queue-export");
    await sleep(500);
  }
  await page.waitForFunction(() => document.querySelectorAll(".q-item").length === 3, null, { timeout: 8000 });
  must((await page.$$(".q-item")).length === 3 && (await page.textContent("#queue-badge")) === "3", "three items wait, and the header badge shows 3");
  const labels = await page.$$eval(".q-label", (els) => els.map((e) => e.textContent));
  must(/0:00–0:02/.test(labels[0]) && /0:02–0:05/.test(labels[1]) && /0:01–0:04/.test(labels[2]), "each item remembers its own selection: " + labels.join(" | "));

  await page.locator(".q-item").nth(2).locator("button[title='Move up']").click();
  await sleep(700);
  const after = (await queue()).items.map((i) => i.label);
  must(/0:01–0:04/.test(after[1]) && /0:02–0:05/.test(after[2]), "Move up reorders the waiting items");
  await page.locator(".q-item").nth(2).locator(".q-cancel").click();
  await sleep(700);
  must((await queue()).items[2].state === "cancelled", "a waiting item can be cancelled");

  await page.click("#btn-queue-pause"); // resume
  await page.waitForFunction(() => [...document.querySelectorAll(".q-item")].filter((e) => e.classList.contains("q-done")).length === 2, null, { timeout: 240000 });
  const q = await queue();
  must(q.items.filter((i) => i.state === "done").length === 2 && existsSync(join(out, q.items[0].result.video)), "the two remaining items were exported, in order");
  await page.click("#btn-queue-clear");
  await page.waitForFunction(() => document.querySelectorAll(".q-item").length === 0, null, { timeout: 8000 });
  must(true, "Clear finished empties the list");
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
