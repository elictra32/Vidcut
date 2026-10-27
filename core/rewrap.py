"""Re-flow every subtitle to a chosen number of characters per line (and lines per subtitle), breaking only between
words. A subtitle that no longer fits is split into several, with the time shared out by text length."""
import dataclasses
import uuid

from core.models import Subtitle
from core.thai_split import Token, build_lines, tokens_to_words

NO_LIMIT = 1e9


def _flatten(text: str) -> str:
    """The text on one line: a line break between two Latin words becomes a space, anywhere else it vanishes."""
    out = []
    parts = text.split("\n")
    for i, part in enumerate(parts):
        part = part.strip()
        if not part:
            continue
        if out and out[-1][-1:].isascii() and out[-1][-1:].isalnum() and part[:1].isascii() and part[:1].isalnum():
            out.append(" ")
        out.append(part)
    return "".join(out)


def rewrap_subtitles(subs: list[Subtitle], line_width: int, max_lines: int) -> list[Subtitle]:
    out: list[Subtitle] = []
    for s in subs:
        text = _flatten(s.text)
        if not text:
            out.append(s)
            continue
        words = tokens_to_words([Token(text, s.src_start, s.src_end)])
        lines = build_lines(words, line_width, max_lines, max_pause=NO_LIMIT, max_duration=NO_LIMIT)
        if len(lines) <= 1:
            out.append(dataclasses.replace(s, text=lines[0].text if lines else text))
            continue
        for k, ln in enumerate(lines):
            # keep the original span's ends exact; inner boundaries come from the words' share of the time
            start = s.src_start if k == 0 else ln.start
            end = s.src_end if k == len(lines) - 1 else ln.end
            out.append(dataclasses.replace(s, id=s.id if k == 0 else uuid.uuid4().hex, src_start=start,
                                           src_end=max(end, start + 0.05), text=ln.text))
    return out
