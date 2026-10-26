"""Turn Whisper's sub-word tokens into Thai words (PyThaiNLP newmm) and build
subtitle lines that only break between words."""
import unicodedata
from dataclasses import dataclass

from pythainlp.tokenize import word_tokenize


@dataclass
class Token:
    text: str
    start: float
    end: float


@dataclass
class Word:
    text: str
    start: float
    end: float
    space_before: bool = False


@dataclass
class Line:
    text: str
    start: float
    end: float


def display_width(s: str) -> int:
    return sum(1 for ch in s if unicodedata.category(ch) != "Mn")


def tokens_to_words(tokens: list[Token]) -> list[Word]:
    # Spread each token's time evenly over its characters.
    chars: list[tuple[str, float, float]] = []
    for t in tokens:
        n = max(1, len(t.text))
        step = (t.end - t.start) / n
        for i, ch in enumerate(t.text):
            chars.append((ch, t.start + i * step, t.start + (i + 1) * step))
    text = "".join(c for c, _, _ in chars)
    words, pos, pending_space = [], 0, False
    for piece in word_tokenize(text, engine="newmm", keep_whitespace=True):
        span = chars[pos:pos + len(piece)]
        pos += len(piece)
        if not piece.strip():
            pending_space = True
            continue
        text_piece = piece.strip()
        marks = len(text_piece) - len(text_piece.lstrip("".join(chr(c) for c in range(0x0E31, 0x0E3B))
                                                       + "".join(chr(c) for c in range(0x0E47, 0x0E4F))))
        if words and not pending_space and marks:
            # a vowel/tone mark can't start a word: newmm sometimes splits an unusual cluster ("อือ" | "ืคน");
            # hand the mark(s) back to the word they belong to
            prev = words[-1]
            words[-1] = Word(prev.text + text_piece[:marks], prev.start, prev.end, prev.space_before)
            text_piece = text_piece[marks:]
            if not text_piece:
                continue
        words.append(Word(text_piece, span[0][1], span[-1][2], space_before=pending_space))
        pending_space = False
    return words


def _row_text(row: list[Word]) -> str:
    return "".join((" " if w.space_before and i else "") + w.text for i, w in enumerate(row))


def build_lines(words: list[Word], line_width: int, max_lines: int, max_pause: float = 0.8,
                max_duration: float = 6.0) -> list[Line]:
    lines: list[Line] = []
    rows: list[list[Word]] = [[]]

    def flush():
        ws = [w for r in rows for w in r]
        if ws:
            lines.append(Line("\n".join(_row_text(r) for r in rows if r), ws[0].start, ws[-1].end))

    for w in words:
        cur = [x for r in rows for x in r]
        if cur and (w.start - cur[-1].end > max_pause or w.end - cur[0].start > max_duration):
            flush()
            rows = [[]]
        row = rows[-1]
        if row and display_width(_row_text(row + [w])) > line_width:
            if len(rows) < max_lines:
                rows.append([w])
            else:
                flush()
                rows = [[w]]
        else:
            row.append(w)
    flush()
    return lines
