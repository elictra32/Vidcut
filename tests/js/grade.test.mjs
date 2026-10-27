import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { gradeMatrix, gradeParams, isNeutral } from "../../web/grade.js";

const CASES = JSON.parse(readFileSync(new URL("../fixtures/grade_cases.json", import.meta.url)));

test("the preview's colour numbers equal the ones the export uses (shared fixture with core/grade.py)", () => {
  for (const c of CASES) {
    const p = gradeParams(c.grade);
    for (const k of Object.keys(c.params)) assert.ok(Math.abs(p[k] - c.params[k]) < 1e-9, `${k} for ${JSON.stringify(c.grade)}`);
  }
});

test("a neutral grade is the identity matrix, and warmth moves red and blue in opposite directions", () => {
  assert.ok(isNeutral({ temperature: 0, tint: 0, brightness: 0, contrast: 0, saturation: 0 }));
  const id = gradeMatrix({});
  assert.deepEqual(id.map((v) => +v.toFixed(6)), [1, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 1, 0]);
  const cool = gradeMatrix({ temperature: -50 });
  assert.ok(cool[0] < 1 && cool[12] > 1);
});
