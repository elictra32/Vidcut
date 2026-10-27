"""Pick candidate highlight moments for short clips without any AI: windows of whole subtitle lines, scored by how
many telling words they contain (per category) and by how loud and dense the speech is. Editable word lists; a
transcript + prompt export lets an AI judge the meaning instead (see transcript_for_ai)."""
import math
import re
from dataclasses import dataclass, field

from core.models import Subtitle
from core.timeline import subtitle_edited_span

CATEGORIES = ("scold", "wisdom", "funny", "general")
LABELS = {"scold": "Scolding", "wisdom": "Wake-up call", "funny": "Funny", "general": "Energetic"}

# Starting word lists (substring match on the Thai text). The user can replace them per request.
LEXICON = {
    "scold": ["โง่", "ควาย", "เหี้ย", "สัส", "เชี่ย", "ห่า", "ไอ้", "บ้าเหรอ", "บ้าไปแล้ว", "ไม่ได้เรื่อง", "ไม่เอาไหน",
              "ขี้เกียจ", "ขี้แพ้", "ไร้สาระ", "โคตร", "ทำไมไม่", "เลิกบ่น", "หยุดโทษ", "ไม่รู้จักโต", "น่าอาย"],
    "wisdom": ["ตื่น", "ลองคิดดู", "คิดดูสิ", "ความจริง", "ชีวิต", "อนาคต", "จำไว้", "อย่าลืม", "สุดท้าย", "ความฝัน",
               "ความรับผิดชอบ", "ตัวเอง", "เลือกได้", "ไม่มีใคร", "ถ้าไม่เปลี่ยน", "ล้มเหลว", "ความสำเร็จ", "วินัย",
               "ลงมือ", "เสียเวลา", "ข้ออ้าง", "ยอมรับ"],
    "funny": ["ฮ่า", "ขำ", "ตลก", "หัวเราะ", "555", "ฮิ", "มุก"],
}
LAUGH = re.compile(r"5{3,}|ฮ่า+|ฮ่าๆ")
MIN_HITS = {"scold": 2, "wisdom": 2, "funny": 2}


@dataclass
class Line:
    start: float  # edited time
    end: float
    text: str


@dataclass
class Candidate:
    start: float
    end: float
    category: str
    score: float
    hits: int
    text: str = ""
    label: str = field(default="", repr=False)

    @property
    def duration(self) -> float:
        return self.end - self.start


def lines_from_project(clips, subs: list[Subtitle]) -> list[Line]:
    out = []
    for s in subs:
        span = subtitle_edited_span(clips, s)
        if span and s.text.strip():
            out.append(Line(span[0], span[1], s.text.replace("\n", " ").strip()))
    return sorted(out, key=lambda ln: ln.start)


def count_hits(text: str, words: list[str]) -> int:
    n = sum(text.count(w) for w in words if w)
    return n + (len(LAUGH.findall(text)) if "555" in words else 0)


def _windows(lines: list[Line], min_s: float, max_s: float):
    """(i, j) line ranges whose length is within [min_s, max_s]; ends of the timeline may be shorter."""
    seen = set()
    for i, first in enumerate(lines):
        for target in (min_s, (min_s + max_s) / 2, max_s):
            j = i
            while j + 1 < len(lines) and lines[j + 1].end - first.start <= target:
                j += 1
            dur = lines[j].end - first.start
            if dur >= min_s * 0.8 and dur <= max_s and (i, j) not in seen:
                seen.add((i, j))
                yield i, j


def _overlap(a: Candidate, b: Candidate) -> float:
    inter = max(0.0, min(a.end, b.end) - max(a.start, b.start))
    return inter / min(a.duration, b.duration)


def find_highlights(lines: list[Line], loudness: list[float] | None = None, *, min_s: float = 30.0, max_s: float = 90.0,
                    per_category: int = 5, lexicon: dict[str, list[str]] | None = None) -> list[Candidate]:
    """Best non-overlapping windows per category, most promising first within each. `loudness` = RMS per second of
    the edited timeline (optional); loud, dense stretches get a boost."""
    lex = {k: (lexicon or {}).get(k, LEXICON[k]) for k in LEXICON}
    if not lines:
        return []
    mean_loud = (sum(loudness) / len(loudness)) if loudness else 0.0

    def loud_factor(a, b):
        if not loudness or mean_loud <= 0:
            return 1.0
        seg = loudness[int(a): max(int(a) + 1, int(math.ceil(b)))]
        return min(2.0, max(0.5, (sum(seg) / len(seg)) / mean_loud)) if seg else 1.0

    pools: dict[str, list[Candidate]] = {c: [] for c in CATEGORIES}
    for i, j in _windows(lines, min_s, max_s):
        a, b = lines[i].start, lines[j].end
        text = " ".join(ln.text for ln in lines[i:j + 1])
        minutes = (b - a) / 60
        lf = loud_factor(a, b)
        for cat in ("scold", "wisdom", "funny"):
            hits = count_hits(text, lex[cat])
            if hits >= MIN_HITS[cat]:
                pools[cat].append(Candidate(a, b, cat, hits / minutes * lf, hits, text))
        chars_per_s = len(re.sub(r"\s", "", text)) / (b - a)
        pools["general"].append(Candidate(a, b, "general", chars_per_s * lf, 0, text))
    out = []
    for cat in CATEGORIES:
        chosen: list[Candidate] = []
        for cand in sorted(pools[cat], key=lambda c: -c.score):
            if all(_overlap(cand, k) < 0.3 for k in chosen):
                cand.label = LABELS[cat]
                chosen.append(cand)
            if len(chosen) >= per_category:
                break
        out += chosen
    return out


def find_shots(lines: list[Line], loudness: list[float] | None = None, *, categories=("scold", "wisdom", "funny"),
               lexicon: dict[str, list[str]] | None = None, pad_s: float = 1.5, merge_gap_s: float = 6.0, min_hits: int = 1,
               min_len: float = 3.0, max_len: float = 45.0, limit: int = 300) -> list[Candidate]:
    """EVERY short stretch around telling words, for gathering a reel ("all the scolding in the video"): lines that contain
    the words, joined when they are close together, with a little padding either side. Returned in time order."""
    lex = {k: (lexicon or {}).get(k, LEXICON[k]) for k in LEXICON}
    if not lines:
        return []
    total = lines[-1].end
    mean_loud = (sum(loudness) / len(loudness)) if loudness else 0.0

    def loud_factor(a, b):
        if not loudness or mean_loud <= 0:
            return 1.0
        seg = loudness[int(a): max(int(a) + 1, int(math.ceil(b)))]
        return min(2.0, max(0.5, (sum(seg) / len(seg)) / mean_loud)) if seg else 1.0

    out: list[Candidate] = []
    for cat in categories:
        if cat not in lex:
            continue
        clusters: list[list[tuple[Line, int]]] = []
        for ln in lines:
            hits = count_hits(ln.text, lex[cat])
            if not hits:
                continue
            cur = clusters[-1] if clusters else None
            if cur and ln.start - cur[-1][0].end <= merge_gap_s and ln.end - cur[0][0].start <= max_len:
                cur.append((ln, hits))
            else:
                clusters.append([(ln, hits)])
        found = []
        for cl in clusters:
            n_hits = sum(h for _, h in cl)
            if n_hits < min_hits:
                continue
            a, b = max(0.0, cl[0][0].start - pad_s), min(total, cl[-1][0].end + pad_s)
            if b - a < min_len:  # a one-word shot still needs a moment of context
                mid = (a + b) / 2
                a, b = max(0.0, mid - min_len / 2), min(total, mid + min_len / 2)
            text = " ".join(ln.text for ln in lines if ln.end > a and ln.start < b)
            found.append(Candidate(a, b, cat, n_hits / ((b - a) / 60) * loud_factor(a, b), n_hits, text, LABELS[cat]))
        best = sorted(found, key=lambda c: -c.score)[:limit]
        out += sorted(best, key=lambda c: c.start)
    return out


def transcript_for_ai(lines: list[Line]) -> str:
    def mmss(t):
        h, rem = divmod(int(t), 3600)
        m, s = divmod(rem, 60)
        return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"
    body = "\n".join(f"[{mmss(ln.start)}] {ln.text}" for ln in lines)
    prompt = (
        "ด้านล่างคือถอดเสียงของวิดีโอคอร์ส (เวลาเป็นรูปแบบ [นาที:วินาที] ของวิดีโอที่ตัดช่วงเงียบแล้ว)\n"
        "ช่วยเลือกช่วงที่เหมาะทำคลิปสั้นยาว 30–90 วินาที โดยจัดเป็นหมวด:\n"
        "- scold: ช่วงที่ผู้สอนด่า/ดุผู้เรียนแบบมันส์ ๆ\n"
        "- wisdom: ช่วงเตือนสติ/ประโยคคมที่คนอยากแชร์\n"
        "- funny: ช่วงขำ/มุกตลก\n"
        "- other: ช่วงน่าสนใจอื่น ๆ ที่เล่าจบในตัวเอง\n"
        "เลือกช่วงที่เริ่มและจบที่ประโยคสมบูรณ์ ไม่ซ้อนทับกัน หมวดละไม่เกิน 5 ช่วง\n"
        "ตอบเป็นบรรทัดเดียวต่อช่วง รูปแบบนี้เท่านั้น: `MM:SS-MM:SS | หมวด | เหตุผลสั้น ๆ`\n\n"
        "=== ถอดเสียง ===\n")
    return prompt + body + "\n"
