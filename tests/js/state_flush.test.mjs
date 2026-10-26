// The page saves edits to the server in the background. Anything that asks the server to act on the
// project (transcribe, export, estimate, import) calls flush() first, and must be able to trust it.
import test from "node:test";
import assert from "node:assert/strict";

const fakeEl = () => ({ className: "", children: [], setAttribute() {}, append(...c) { this.children.push(...c); }, addEventListener() {}, remove() {} });
globalThis.document = { querySelector: () => fakeEl(), createElement: fakeEl, createTextNode: (t) => ({ t }) };
globalThis.Node = class {};

const SERVER = () => ({ clips: [], selection: null, subtitles: [], style: {}, preset: "tiktok", export: {}, rev: 0 });
const state = await import("../../web/state.js");
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/** A fake server whose PUT takes `putMs` and can be told to fail. */
function fakeServer({ putMs = 0, status = 200, error = null } = {}) {
  const log = { puts: [], done: 0, project: SERVER() };
  globalThis.fetch = async (url, opts = {}) => {
    const json = (data, s = 200) => ({ ok: s < 400, status: s, json: async () => data });
    if (opts.method === "PUT") {
      log.puts.push(JSON.parse(opts.body));
      await sleep(putMs);
      if (status >= 400) return json({ error: error ?? { code: "boom", message: "x" } }, status);
      log.project = JSON.parse(opts.body);
      log.done++;
      return json({ ok: true });
    }
    return json({ project: structuredClone(log.project), presets: {}, fonts: [] }); // a copy, like a real response
  };
  return log;
}

test("flush waits for a save that is already in flight", async () => {
  const server = fakeServer({ putMs: 200 });
  await state.loadProject();
  state.update((p) => (p.selection = { start: 1, end: 2 }));
  await sleep(450); // the 400 ms debounce fired: the PUT is now on its way, dirty is already false
  assert.equal(server.done, 0);
  assert.equal(await state.flush(), true);
  assert.equal(server.done, 1, "flush returned before the server had stored the selection");
  assert.deepEqual(server.project.selection, { start: 1, end: 2 });
});

test("flush also saves an edit made while the previous save was in flight", async () => {
  const server = fakeServer({ putMs: 150 });
  await state.loadProject();
  state.update((p) => (p.selection = { start: 1, end: 2 }));
  await sleep(450);
  state.update((p) => (p.selection = { start: 3, end: 4 }));
  assert.equal(await state.flush(), true);
  assert.deepEqual(server.project.selection, { start: 3, end: 4 });
});

test("flush with nothing to save is true and does not call the server", async () => {
  const server = fakeServer();
  await state.loadProject();
  assert.equal(await state.flush(), true);
  assert.equal(server.puts.length, 0);
});

test("a failed save makes flush false (callers must not act on stale server state) and is retried next time", async () => {
  const server = fakeServer({ status: 500 });
  await state.loadProject();
  state.update((p) => (p.selection = { start: 5, end: 6 }));
  assert.equal(await state.flush(), false);
  server.puts.length = 0;
  assert.equal(await state.flush(), false);
  assert.equal(server.puts.length, 1, "the unsaved edit was forgotten instead of retried");
});

test("a stale save (a job changed the project) reloads the server's version and reports false", async () => {
  const server = fakeServer({ status: 409, error: { code: "project_stale", message: "stale" } });
  server.project.rev = 7;
  await state.loadProject();
  state.update((p) => (p.selection = { start: 1, end: 2 }));
  assert.equal(await state.flush(), false);
  assert.equal(state.getProject().rev, 7);
  assert.equal(state.getProject().selection, null, "the server's project replaces the page's");
});
