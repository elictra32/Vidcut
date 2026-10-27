import test from "node:test";
import assert from "node:assert/strict";
import { deleteKeepAt, keepOnly, removeRange, splitKeeps } from "../../web/cut_ops.js";

const K = (start, end, enabled = true) => ({ start, end, enabled });

test("splitKeeps splits inside an enabled keep and nowhere else", () => {
  assert.deepEqual(splitKeeps([K(0, 10), K(20, 30)], 4), [K(0, 4), K(4, 10), K(20, 30)]);
  assert.equal(splitKeeps([K(0, 10), K(20, 30)], 15), null);            // inside a gap
  assert.equal(splitKeeps([K(0, 10, false)], 5), null);                 // inside a disabled keep
  assert.equal(splitKeeps([K(0, 10)], 0.01), null);                     // would leave a sliver
});

test("deleteKeepAt disables the keep under the time, leaving the others", () => {
  assert.deepEqual(deleteKeepAt([K(0, 4), K(4, 10)], 6), [K(0, 4), K(4, 10, false)]);
  assert.equal(deleteKeepAt([K(0, 4)], 9), null);
});

test("removeRange cuts a range out across keeps, keeping the outer parts", () => {
  assert.deepEqual(removeRange([K(0, 10), K(20, 30)], 5, 25), [K(0, 5), K(5, 10, false), K(20, 25, false), K(25, 30)]);
  assert.deepEqual(removeRange([K(0, 10)], 0, 10), [K(0, 10, false)]);
  assert.equal(removeRange([K(0, 10)], 12, 15), null);                  // nothing there to remove
  assert.equal(removeRange([K(0, 10)], 5, 5.01), null);                 // too short
});

test("a removed range stays removed when removed again", () => {
  const once = removeRange([K(0, 10)], 2, 6);
  assert.equal(removeRange(once, 2, 6), null);
});

test("keepOnly leaves just the wanted ranges enabled and keeps the rest restorable", () => {
  assert.deepEqual(keepOnly([K(0, 100)], [K(10, 20), K(50, 60)]),
    [K(0, 10, false), K(10, 20), K(20, 50, false), K(50, 60), K(60, 100, false)]);
  assert.deepEqual(keepOnly([K(0, 10), K(20, 30), K(40, 50, false)], [K(5, 25)]),
    [K(0, 5, false), K(5, 10), K(20, 25), K(25, 30, false), K(40, 50, false)]);
  assert.deepEqual(keepOnly([K(0, 10)], []), [K(0, 10, false)]);          // a clip with no shot drops out
  assert.deepEqual(keepOnly([K(0, 10)], [K(0, 10)]), [K(0, 10)]);
});
