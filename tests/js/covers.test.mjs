import test from "node:test";
import assert from "node:assert/strict";
import { parseTitles, thaiDate } from "../../web/covers.js";

test("thaiDate gives the Buddhist-era text used on the covers", () => {
  assert.equal(thaiDate("2026-10-22"), "วันที่ 22 ตุลาคม  2569");
  assert.equal(thaiDate("2026-09-23"), "วันที่ 23 กันยายน  2569");
});

test("parseTitles reads one title per line with an optional date after |", () => {
  assert.deepEqual(parseTitles("A\n\n  B | วันที่ 5 พฤศจิกายน  2569 \n | ignored\n"), [
    { title: "A" }, { title: "B", date_text: "วันที่ 5 พฤศจิกายน  2569" }]);
});
