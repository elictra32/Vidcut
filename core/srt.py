"""SRT parsing (as exported by YouTube Studio and most tools)."""
import html
import re
from dataclasses import dataclass

_TIME = re.compile(r"(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})\s*-->\s*(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})")
_TAG = re.compile(r"<[^>]+>")


@dataclass
class Cue:
    start: float  # seconds
    end: float
    text: str


def _seconds(h, m, s, ms) -> float:
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms.ljust(3, "0")) / 1000


def parse_srt(text: str) -> list[Cue]:
    """Cues in file order. Blocks without a valid time range, with end <= start, or without text are skipped."""
    text = text.lstrip("﻿").replace("\r\n", "\n").replace("\r", "\n")
    cues = []
    for block in re.split(r"\n\s*\n", text.strip()):
        lines = block.split("\n")
        for i, line in enumerate(lines):
            m = _TIME.search(line)
            if m:
                break
        else:
            continue
        start, end = _seconds(*m.groups()[:4]), _seconds(*m.groups()[4:])
        if end <= start:
            continue
        body = "\n".join(ln.strip() for ln in lines[i + 1:] if ln.strip())
        body = html.unescape(_TAG.sub("", body)).strip()
        if body:
            cues.append(Cue(start, end, body))
    return cues
