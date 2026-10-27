import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { revealEnds, revealedCount } from "../../web/reveal.js";

const cases = JSON.parse(readFileSync(new URL("../fixtures/reveal_cases.json", import.meta.url)));

test("revealEnds matches the shared fixture", () => {
  for (const c of cases) assert.deepEqual(revealEnds(c.text), c.ends, JSON.stringify(c.text));
});

test("text grows over time and is complete before the line ends", () => {
  const text = "สวัสดีครับ";
  const seen = [0, 0.1, 0.5, 1, 1.5, 1.9].map((t) => revealedCount(text, 0, 2, t));
  assert.deepEqual(seen, [...seen].sort((a, b) => a - b));
  assert.ok(seen[0] >= 1 && seen[0] < Array.from(text).length);
  assert.equal(revealedCount(text, 0, 2, 1.9), Array.from(text).length);
});
