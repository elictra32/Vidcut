// Split into episodes: plan table, then export every episode; own intro each, files numbered.
import { join } from "node:path";
import { chromium, makeWebm, startApp, must } from "./harness.mjs";

const app = await startApp();
let browser, failed = false;
try {
  const json = { "Content-Type": "application/json" };
  const add = async (name, secs) => {
    const path = join(app.work, name);
    makeWebm(path, secs, "sin(2*PI*440*t)", { size: "320x180" });
    return (await (await fetch(`${app.base}/api/clips`, { method: "POST", headers: json, body: JSON.stringify({ path }) })).json()).clip.id;
  };
  const main = await add("main.webm", 60), i1 = await add("i1.webm", 2), i2 = await add("i2.webm", 3), outro = await add("out.webm", 1);
  const p = (await (await fetch(`${app.base}/api/project`)).json()).project;
  const roles = { [i1]: "intro", [i2]: "intro", [outro]: "outro" };
  p.clips.forEach((c) => (c.role = roles[c.id] ?? "main"));
  await fetch(`${app.base}/api/project`, { method: "PUT", headers: json, body: JSON.stringify(p) });

  browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  const problems = [];
  page.on("console", (m) => m.type() === "error" && problems.push(m.text()));
  page.on("pageerror", (e) => problems.push(e.message));
  page.on("dialog", (d) => d.accept());
  await page.goto(app.base);
  await page.waitForSelector("#btn-plan-eps");
  const tags = await page.$$eval(".role-tag", (els) => els.map((e) => e.textContent));
  must(JSON.stringify(tags) === JSON.stringify(["Intro for EP 1", "Intro for EP 2", "Outro: end of every EP"]), "the clip list says which intro is for which episode: " + tags.join(" | "));
  await page.fill("#ep-limit", "5");
  await page.click("#btn-plan-eps");
  await page.waitForSelector(".ep-table tr:nth-child(3)", { timeout: 10000 });
  must((await page.$$(".ep-table tr")).length === 3, "the plan shows two episodes (plus the header row)");
  must((await page.$$(".ep-intro-pick")).length === 2, "each episode row has an intro picker");
  await page.locator(".ep-intro-pick").first().selectOption({ index: 2 }); // episode 1 takes the second intro
  await page.click("#btn-export-eps");
  await page.waitForSelector(".ep-file", { timeout: 280000 });
  must((await page.$$(".ep-file")).length === 2, "both episodes were exported");
  const names = await page.$$eval(".ep-file", (els) => els.map((e) => e.textContent));
  must(/EP01/.test(names[0]) && /EP02/.test(names[1]), "files are numbered EP01, EP02: " + names.join(" | "));
  must(!names.some((n) => /over the/.test(n)), "no episode is over the limit");
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
