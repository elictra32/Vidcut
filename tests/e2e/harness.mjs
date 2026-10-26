// Shared by the e2e scripts: start the real server on a free port, make synthetic WebM clips.
import { spawn, spawnSync } from "node:child_process";
import { mkdtempSync, rmSync } from "node:fs";
import { createServer } from "node:net";
import { tmpdir } from "node:os";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url); // honours NODE_PATH, unlike ESM import
export const { chromium } = require("playwright");
export const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
export const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
export const must = (cond, msg) => { if (!cond) throw new Error("ASSERT: " + msg); console.log("ok  -", msg); };

const freePort = () => new Promise((res) => { const s = createServer().listen(0, () => { const p = s.address().port; s.close(() => res(p)); }); });

/** A WebM (VP8/Opus: Playwright's Chromium has no H.264). `pattern` = aevalsrc expression for the audio. */
export function makeWebm(path, seconds, pattern = "sin(2*PI*440*t)", { size = "640x360", gop = 25, kbps = 300 } = {}) {
  const r = spawnSync("ffmpeg", ["-y", "-hide_banner", "-loglevel", "error",
    "-f", "lavfi", "-i", `testsrc2=size=${size}:rate=25:duration=${seconds}`,
    "-f", "lavfi", "-i", `aevalsrc=${pattern}:s=48000:d=${seconds}`,
    "-c:v", "libvpx", "-b:v", `${kbps}k`, "-g", String(gop), "-cpu-used", "8", "-deadline", "realtime",
    "-c:a", "libopus", "-shortest", path]);
  if (r.status !== 0) throw new Error("could not generate a test clip: " + r.stderr);
}

export async function startApp(extraEnv = {}) {
  const work = mkdtempSync(join(tmpdir(), "vidcut-e2e-"));
  const home = join(work, "home");
  const port = await freePort();
  const server = spawn(process.env.VIDCUT_PYTHON || "python", ["-m", "server.app"], {
    cwd: ROOT, stdio: ["ignore", "pipe", "pipe"],
    env: { ...process.env, VIDCUT_HOME: home, VIDCUT_PORT: String(port), VIDCUT_NO_BROWSER: "1", ...extraEnv },
  });
  let log = "";
  server.stderr.on("data", (d) => (log += d));
  const base = `http://127.0.0.1:${port}`;
  for (let i = 0; i < 50; i++) {
    try { if ((await fetch(`${base}/api/project`)).ok) break; } catch { /* not up yet */ }
    await sleep(200);
  }
  return { work, home, base, log: () => log, stop() { server.kill(); rmSync(work, { recursive: true, force: true }); } };
}
