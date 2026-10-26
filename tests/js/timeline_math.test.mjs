// Runs the same fixture cases as tests/test_timeline.py against the browser-side port.
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import * as tm from "../../web/timeline_math.js";

const DATA = JSON.parse(readFileSync(new URL("../fixtures/timeline_cases.json", import.meta.url)));

const clipsFor = (name) =>
  DATA.projects[name].map((c) => ({
    id: c.id,
    duration: c.duration,
    keeps: c.keeps.map(([start, end, enabled]) => ({ start, end, enabled })),
  }));

const close = (a, b) => assert.ok(Math.abs(a - b) < 1e-6, `${a} != ${b}`);
function same(got, exp) {
  if (Array.isArray(exp)) {
    assert.ok(Array.isArray(got) && got.length === exp.length, JSON.stringify(got));
    exp.forEach((e, i) => same(got[i], e));
  } else if (typeof exp === "number") close(got, exp);
  else if (exp && typeof exp === "object") {
    assert.ok(got && typeof got === "object", String(got));
    for (const k of Object.keys(exp)) same(got[k], exp[k]);
  } else assert.equal(got, exp);
}

function call(c) {
  const clips = clipsFor(c.project);
  const a = c.args;
  switch (c.fn) {
    case "edited_duration": return tm.editedDuration(clips);
    case "source_to_edited": return tm.sourceToEdited(clips, ...a);
    case "edited_to_source": return tm.editedToSource(clips, ...a);
    case "clamp_to_keep": return tm.clampToKeep(clips, ...a);
    case "selection_pieces":
      return tm.selectionPieces(clips, { start: a[0], end: a[1] }).map((p) => [p.clipId, p.srcStart, p.srcEnd, p.outStart]);
    case "subtitle_edited_span":
      return tm.subtitleEditedSpan(clips, { clip_id: a[0], src_start: a[1], src_end: a[2] });
    default: throw new Error("unknown fn " + c.fn);
  }
}

for (const c of DATA.cases) {
  test(`${c.fn} ${c.project} ${JSON.stringify(c.args)}`, () => same(call(c), c.expect));
}

test("remapSelection keeps the same source content when an earlier keep is cut", () => {
  const before = clipsFor("single");
  const after = clipsFor("single");
  after[0].keeps = [
    { start: 0, end: 3, enabled: false },
    { start: 3, end: 10, enabled: true },
    { start: 20, end: 30, enabled: true },
  ];
  same(tm.remapSelection(before, after, { start: 5, end: 15 }), { start: 2, end: 12 });
});

test("remapSelection clamps a start that falls into a newly cut region", () => {
  const before = clipsFor("single");
  const after = clipsFor("single");
  after[0].keeps = [
    { start: 0, end: 8, enabled: false },
    { start: 8, end: 10, enabled: true },
    { start: 20, end: 30, enabled: true },
  ];
  same(tm.remapSelection(before, after, { start: 5, end: 15 }), { start: 0, end: 7 });
});

test("remapSelection returns null when nothing is left", () => {
  const before = clipsFor("single");
  const after = clipsFor("single");
  after[0].keeps.forEach((k) => (k.enabled = false));
  assert.equal(tm.remapSelection(before, after, { start: 5, end: 15 }), null);
});

test("remapSelection passes null through", () => {
  assert.equal(tm.remapSelection(clipsFor("single"), clipsFor("single"), null), null);
});

// ---- dragEdgeToSource: dragging a subtitle edge on the edited timeline -> source anchor ----
const sub = (clip_id, src_start, src_end) => ({ clip_id, src_start, src_end });

test("dragEdgeToSource: start edge cannot cross the end edge (min length 0.1 s)", () => {
  close(tm.dragEdgeToSource(clipsFor("single"), sub("c1", 5, 8), "start", 12), 7.9);
});

test("dragEdgeToSource: end edge dragged past a cut lands in the later keep", () => {
  close(tm.dragEdgeToSource(clipsFor("single"), sub("c1", 5, 8), "end", 12), 22);
});

test("dragEdgeToSource: edge dragged into another clip clamps to this clip's last keep end", () => {
  close(tm.dragEdgeToSource(clipsFor("multi"), sub("c1", 5, 8), "end", 22), 30);
});

test("dragEdgeToSource: edge dragged before time zero clamps to the first source moment", () => {
  close(tm.dragEdgeToSource(clipsFor("single"), sub("c1", 25, 28), "start", -5), 0);
});

test("dragEdgeToSource: start edge dragged into an earlier clip clamps to this clip's first keep", () => {
  close(tm.dragEdgeToSource(clipsFor("multi"), sub("c2", 1, 3), "start", 5), 0);
});

// ---- nextPlayTarget: what playback does when the loaded clip reaches a source time -------------
test("nextPlayTarget: inside a kept segment keeps playing", () => {
  assert.deepEqual(tm.nextPlayTarget(clipsFor("multi"), "c1", 5), { kind: "play" });
  assert.deepEqual(tm.nextPlayTarget(clipsFor("multi"), "c2", 2), { kind: "play" });
});

test("nextPlayTarget: a gap inside the clip is skipped to the next keep", () => {
  assert.deepEqual(tm.nextPlayTarget(clipsFor("multi"), "c1", 15), { kind: "seek", src: 20 });
});

test("nextPlayTarget: past the last keep hops to the next clip (also when the video has ended)", () => {
  assert.deepEqual(tm.nextPlayTarget(clipsFor("multi"), "c1", 30), { kind: "clip", clipId: "c2", src: 0 });
  assert.deepEqual(tm.nextPlayTarget(clipsFor("multi"), "c1", 100), { kind: "clip", clipId: "c2", src: 0 });
});

test("nextPlayTarget: the last clip's end stops playback", () => {
  assert.deepEqual(tm.nextPlayTarget(clipsFor("multi"), "c2", 5), { kind: "end" });
  assert.deepEqual(tm.nextPlayTarget(clipsFor("single"), "c1", 45), { kind: "end" });
});

test("nextPlayTarget: clips with nothing enabled are skipped", () => {
  const clips = clipsFor("multi");
  clips.splice(1, 0, { id: "mid", duration: 9, keeps: [{ start: 0, end: 9, enabled: false }] });
  assert.deepEqual(tm.nextPlayTarget(clips, "c1", 31), { kind: "clip", clipId: "c2", src: 0 });
});
