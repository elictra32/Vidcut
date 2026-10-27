// Read time ranges out of an AI's answer: lines like "12:30-13:45 | scold | reason" (also "1:02:03 – 1:03:00").
const T = String.raw`(?:\d{1,2}:)?\d{1,2}:\d{2}`;
const RANGE = new RegExp(String.raw`(${T})\s*(?:-|–|—|~|to|ถึง)\s*(${T})`, "i");

export const toSeconds = (s) => s.split(":").map(Number).reduce((acc, v) => acc * 60 + v, 0);

export function parseRanges(text) {
  const out = [];
  for (const line of text.split(/\r?\n/)) {
    const m = RANGE.exec(line);
    if (!m) continue;
    const start = toSeconds(m[1]), end = toSeconds(m[2]);
    if (!(end > start)) continue;
    const rest = line.slice(m.index + m[0].length).replace(/^[\s|:\-–—`*]+/, "");
    const [first, ...more] = rest.split("|").map((x) => x.trim());
    const category = /scold|ด่า/i.test(first) ? "scold" : /wisdom|เตือนสติ/i.test(first) ? "wisdom"
      : /funny|ตลก|ขำ/i.test(first) ? "funny" : "other";
    out.push({ start, end, category, text: (more.join(" | ") || (category === "other" ? first : "")).replace(/[`*]+/g, "").trim() });
  }
  return out;
}
