import test from "node:test";
import assert from "node:assert/strict";
import { cleanItems, thaiDate } from "../../web/covers.js";

test("thaiDate gives the Buddhist-era text used on the covers", () => {
  assert.equal(thaiDate("2026-10-22"), "วันที่ 22 ตุลาคม  2569");
  assert.equal(thaiDate("2026-09-23"), "วันที่ 23 กันยายน  2569");
});

test("cleanItems keeps the line breaks typed inside a title, drops blank lines and empty covers, keeps an own date", () => {
  assert.deepEqual(cleanItems([
    { title: "  Candlestick  and\n\n Price Pattern  ", date: "" },
    { title: "   ", date: "x" },
    { title: "B", date: " วันที่ 5 พฤศจิกายน  2569 " }]), [
    { title: "Candlestick and\nPrice Pattern" }, { title: "B", date_text: "วันที่ 5 พฤศจิกายน  2569" }]);
});
