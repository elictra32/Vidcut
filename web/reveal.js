// Mirror of core/reveal.py (shared fixture tests/fixtures/reveal_cases.json): subtitle text that appears piece by piece.
const LEADING_VOWELS = "เแโใไ";
const REVEAL_SHARE = 0.8;
const MIN_STEP_S = 0.05;

/** Code-point counts after which the text may stop. */
export function revealEnds(text) {
  const chars = Array.from(text);
  const ends = [];
  chars.forEach((ch, idx) => {
    const i = idx + 1, nxt = chars[i];
    if (/\s/u.test(ch) || LEADING_VOWELS.includes(ch)) return;
    if (nxt !== undefined && /\p{Mn}/u.test(nxt)) return;
    ends.push(i);
  });
  if (chars.length && (!ends.length || ends[ends.length - 1] !== chars.length)) ends.push(chars.length);
  return ends;
}

/** How many code points of `text` are visible at time `t` for a line shown over [start, end). */
export function revealedCount(text, start, end, t) {
  const total = Array.from(text).length;
  const ends = revealEnds(text);
  const d = end - start;
  if (!ends.length || d <= 0) return total;
  const window = d * REVEAL_SHARE;
  const group = Math.max(1, Math.ceil(ends.length / Math.max(1, Math.floor(window / MIN_STEP_S))));
  const picks = ends.filter((_, i) => (i + 1) % group === 0);
  if (picks[picks.length - 1] !== ends[ends.length - 1]) picks.push(ends[ends.length - 1]);
  const n = picks.length;
  let shown = picks[0];
  for (let j = 0; j < n; j++) if (t >= start + (window * j) / n - 1e-9) shown = picks[j];
  return shown;
}
