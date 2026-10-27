import test from "node:test";
import assert from "node:assert/strict";
import { parseRanges, toSeconds } from "../../web/ranges.js";

test("toSeconds reads MM:SS and H:MM:SS", () => {
  assert.equal(toSeconds("12:30"), 750);
  assert.equal(toSeconds("1:02:03"), 3723);
});

test("parseRanges reads the requested format and ignores other lines", () => {
  const out = parseRanges("Here are the picks:\n`12:30-13:45 | scold | โดนด่าเรื่องขี้เกียจ`\n- 05:00 – 05:40 | wisdom | คมมาก\n1:02:00 ~ 1:03:10 | funny | ขำ\nnothing here\n20:00-19:00 | other | backwards");
  assert.equal(out.length, 3);
  assert.deepEqual(out.map((r) => [r.start, r.end, r.category]), [[750, 825, "scold"], [300, 340, "wisdom"], [3720, 3790, "funny"]]);
  assert.equal(out[0].text, "โดนด่าเรื่องขี้เกียจ");
});

test("an unknown category falls back to other", () => {
  assert.equal(parseRanges("00:10-00:50 | something | x")[0].category, "other");
});
