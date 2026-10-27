"""Subtitle text that appears piece by piece as it is spoken. A piece is one visible character with the Thai marks
that sit on it; a leading vowel (เ แ โ ใ ไ) is never shown alone. Mirrored by web/reveal.js (shared fixture)."""
import math
import unicodedata

LEADING_VOWELS = "เแโใไ"
REVEAL_SHARE = 0.8  # the text is complete after this share of the line's time and stays until it ends
MIN_STEP_S = 0.05   # never flip the picture faster than this


def reveal_ends(text: str) -> list[int]:
    """Code-point counts after which the text may stop: [..., len(text)]. Empty text -> []."""
    chars = list(text)
    ends = []
    for i, ch in enumerate(chars, 1):
        nxt = chars[i] if i < len(chars) else None
        if ch.isspace() or ch in LEADING_VOWELS:
            continue
        if nxt is not None and unicodedata.category(nxt) == "Mn":
            continue
        ends.append(i)
    if chars and (not ends or ends[-1] != len(chars)):
        ends.append(len(chars))
    return ends


def reveal_schedule(text: str, start: float, end: float) -> list[tuple[float, float, int]]:
    """(from, to, shown code points) steps covering [start, end]. Step j appears at start + window*j/n; the last
    step is the whole text and stays until the line ends."""
    ends = reveal_ends(text)
    d = end - start
    if not ends or d <= 0:
        return [(start, end, len(text))]
    window = d * REVEAL_SHARE
    group = max(1, math.ceil(len(ends) / max(1, int(window / MIN_STEP_S))))
    picks = ends[group - 1::group]
    if picks[-1] != ends[-1]:
        picks.append(ends[-1])
    n = len(picks)
    return [(start + window * j / n, start + window * (j + 1) / n if j < n - 1 else end, shown)
            for j, shown in enumerate(picks)]
