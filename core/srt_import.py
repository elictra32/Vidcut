"""Turn the cues of a YouTube auto-caption SRT into source-anchored subtitles.

YouTube's cues are "rolling": a cue's end is when its line leaves the screen, not when the speech
ended, cues overlap, a sentence is split between cues (even in the middle of a word), and the
file has junk (tags, speaker marks, one-syllable fillers). So: clean the text, derive each cue's
real speech window, then run the same Thai word segmentation and line building as Whisper output."""
import re
import uuid
from dataclasses import dataclass

from core.models import Clip, Selection, Subtitle
from core.presets import Preset
from core.srt import Cue
from core.thai_split import Token, build_lines, tokens_to_words
from core.timeline import selection_pieces

_BRACKET_TAG = re.compile(r"\[[^\]]*\]")  # [เสียงหัวเราะ], [ดนตรี], [Music]
_SPEAKER = re.compile(r">>")
_LEADING_DASH = re.compile(r"^\s*[-–]\s+")
# a cue made only of hesitation sounds ("เออ", "อือื", "อ่ะ", "อื") or a stray syllable; the same sounds
# inside a sentence are speech and are left alone. Only อ/เ/ะ, tone and vowel marks, plus a few fixed
# sounds, so real short words (ดี, ใช่, หา, อา) are never matched.
_FILLER = re.compile(r"(?:[อเืึ่้๊๋ะ]|อึม|อืม|หะ|ฮึ|ฮะ)+")

MIN_WINDOW = 0.8  # seconds: shortest speech window we assume for any cue
SECONDS_PER_CHAR = 0.25  # slowest plausible speaking rate, to cap windows of cues that linger on screen


@dataclass
class Window:
    start: float
    end: float
    text: str


def _is_alnum_ascii(ch: str) -> bool:
    return bool(ch) and ch.isascii() and ch.isalnum()


def _join(parts: list[str]) -> str:
    """Join lines/cues: no space inside Thai, a space only between two ASCII words."""
    out = ""
    for p in parts:
        if out and _is_alnum_ascii(out[-1]) and _is_alnum_ascii(p[:1]):
            out += " "
        out += p
    return out


def clean_cue_text(raw: str) -> str:
    text = _BRACKET_TAG.sub("", raw)
    lines = []
    for line in text.split("\n"):
        line = _LEADING_DASH.sub("", _SPEAKER.sub(" ", line))
        line = re.sub(r"\s+", " ", line).strip()
        if line:
            lines.append(line)
    text = _join(lines)
    if _FILLER.fullmatch(text.replace(" ", "")):
        return ""
    return text


def effective_windows(cues: list[Cue]) -> list[Window]:
    """Real speech window of each shown cue, in time order and non-overlapping.

    Every cue bounds the one before it, including cues whose text is dropped (a filler or a
    [laughter] tag still means the previous sentence is over); only the dropped ones are not returned."""
    items: list[tuple[float, float, str]] = []  # text == "" for cues that are not shown
    for c in sorted(cues, key=lambda c: c.start):
        text = clean_cue_text(c.text)
        if text and items and items[-1][2] == text:
            continue  # YouTube repeats a line while it rolls up
        items.append((c.start, c.end, text))
    out: list[Window] = []
    prev_end = float("-inf")
    for i, (start, end, text) in enumerate(items):
        start = max(start, prev_end)  # equal starts: the later cue follows the earlier one
        if i + 1 < len(items) and items[i + 1][0] > start:
            end = min(end, items[i + 1][0])  # the next line appearing is when this one's speech is over
        end = min(end, start + max(MIN_WINDOW, SECONDS_PER_CHAR * len(text.replace(" ", ""))))
        end = max(end, start + 0.05)
        prev_end = end
        if text:
            out.append(Window(start, end, text))
    return out


def cues_to_subtitles(clips: list[Clip], clip_id: str, cues: list[Cue], preset: Preset, offset: float = 0.0,
                      selection: Selection | None = None) -> list[Subtitle]:
    """Subtitles anchored to `clip_id`'s source time. With `selection`, only cues inside the source
    ranges the selection covers (a selection spanning cuts covers several ranges)."""
    clip = next(c for c in clips if c.id == clip_id)
    windows = []
    for w in effective_windows([Cue(c.start + offset, c.end + offset, c.text) for c in cues]):
        start, end = max(0.0, w.start), min(clip.duration, w.end)
        if end - start > 0.01:
            windows.append(Window(start, end, w.text))
    if selection is not None:
        ranges = [(p.src_start, p.src_end) for p in selection_pieces(clips, selection) if p.clip_id == clip_id]
        windows = [w for w in windows if any(w.start < b and w.end > a for a, b in ranges)]
    tokens, prev = [], ""
    for w in windows:
        glue = " " if _is_alnum_ascii(prev[-1:]) and _is_alnum_ascii(w.text[:1]) else ""
        tokens.append(Token(glue + w.text, w.start, w.end))
        prev = w.text
    lines = build_lines(tokens_to_words(tokens), preset.line_width, preset.max_lines)
    return [Subtitle(uuid.uuid4().hex, clip_id, ln.start, max(ln.end, ln.start + 0.05), ln.text) for ln in lines]
