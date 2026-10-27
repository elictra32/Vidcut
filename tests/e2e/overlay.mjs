// A logo/photo: added through the panel, painted above the video, draggable and resizable, saved.
import { spawnSync } from "node:child_process";
import { join } from "node:path";
import { chromium, makeWebm, startApp, must, sleep } from "./harness.mjs";

const work0 = process.env.TMPDIR || "/tmp";
const logo = join(work0, `vidcut-logo-${process.pid}.png`);
spawnSync("ffmpeg", ["-y", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=red:s=200x100", "-frames:v", "1", logo]);
const app = await startApp({ VIDCUT_PICK_IMAGE_OVERRIDE: logo });
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
  await page.waitForSelector("#btn-add-overlay");
  await page.click("#btn-add-overlay");
  await page.waitForSelector("#ov-layer img.ov", { timeout: 10000 });
  must(true, "the image appears on the preview");
  const hit = await page.evaluate(() => {
    const r = document.querySelector("#ov-layer img.ov").getBoundingClientRect();
    const e = document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2);
    return e?.classList.contains("ov");
  });
  must(hit, "the image is painted above the video");
  const saved = async () => (await (await fetch(`${app.base}/api/project`)).json()).project.overlays[0];
  const box = await (await page.$("#ov-layer img.ov")).boundingBox();
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  await page.mouse.down();
  await page.mouse.move(box.x - 150, box.y + 200, { steps: 5 });
  await page.mouse.up();
  await sleep(800);
  const moved = await saved();
  must(moved.x < 0.88 && moved.y > 0.1, `dragging moves the image (x=${moved.x}, y=${moved.y})`);
  const w0 = moved.width;
  const box2 = await (await page.$("#ov-layer img.ov")).boundingBox();
  await page.mouse.move(box2.x + box2.width / 2, box2.y + box2.height / 2);
  await page.mouse.wheel(0, -300);
  await sleep(800);
  must((await saved()).width > w0, "the mouse wheel enlarges the image");
  await page.locator(".ov-row input[type=range]").nth(1).evaluate((i) => { i.value = 0.5; i.dispatchEvent(new Event("input")); });
  await sleep(800);
  must((await saved()).opacity === 0.5, "the opacity slider is saved");
  await page.click(".ov-row button[title^='Remove']");
  await page.waitForSelector("#ov-layer img.ov", { state: "detached", timeout: 5000 });
  must((await saved()) === undefined, "removing the image deletes it from the project");
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
