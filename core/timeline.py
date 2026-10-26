"""Time mapping between source time (per clip) and edited time (enabled keeps of all
clips concatenated in order). Subtitles are anchored to source time; everything in
edited time is derived here."""
from dataclasses import dataclass

from core.models import Clip, Keep, Selection, Subtitle

EPS = 1e-9


@dataclass
class Piece:
    clip_id: str
    src_start: float
    src_end: float
    out_start: float  # offset inside the selection output


def enabled_keeps(clip: Clip) -> list[Keep]:
    return sorted((k for k in clip.keeps if k.enabled), key=lambda k: k.start)


def main_clips(clips):
    """The clips on the edit timeline. Intro/outro clips are joined around the selection at export."""
    return [c for c in clips if c.role == "main"]


def _segments(clips):
    """Yield (clip_id, keep, edited_start) for every enabled keep of the main clips, in edited order."""
    t = 0.0
    for c in main_clips(clips):
        for k in enabled_keeps(c):
            yield c.id, k, t
            t += k.end - k.start


def edited_duration(clips: list[Clip]) -> float:
    return sum(k.end - k.start for c in main_clips(clips) for k in enabled_keeps(c))


def source_to_edited(clips, clip_id, src_t) -> float | None:
    for cid, k, e in _segments(clips):
        if cid == clip_id and k.start - EPS <= src_t <= k.end + EPS:
            return e + (src_t - k.start)
    return None


def edited_to_source(clips, t) -> tuple[str, float]:
    segs = list(_segments(clips))
    if not segs:
        raise ValueError("no_keeps")
    for cid, k, e in segs:
        if t < e + (k.end - k.start) - EPS:
            return cid, k.start + max(0.0, t - e)
    cid, k, _ = segs[-1]
    return cid, k.end


def clamp_to_keep(clips, clip_id, src_t) -> float:
    clip = next(c for c in clips if c.id == clip_id)
    keeps = enabled_keeps(clip)
    if not keeps:
        return src_t
    for k in keeps:
        if k.start <= src_t <= k.end:
            return src_t
    bounds = [b for k in keeps for b in (k.start, k.end)]
    return min(bounds, key=lambda b: (abs(b - src_t), b))


def selection_pieces(clips, sel: Selection) -> list[Piece]:
    total = edited_duration(clips)
    if total <= 0 or sel.start < 0 or sel.start >= sel.end or sel.end > total + 1e-6:
        raise ValueError("selection_invalid")
    pieces = []
    for cid, k, e in _segments(clips):
        seg_end = e + (k.end - k.start)
        lo, hi = max(sel.start, e), min(sel.end, seg_end)
        if hi - lo > EPS:
            pieces.append(Piece(cid, k.start + (lo - e), k.start + (hi - e), lo - sel.start))
    return pieces


def selection_time_to_source(pieces: list[Piece], t: float) -> tuple[str, float]:
    for p in pieces:
        if t < p.out_start + (p.src_end - p.src_start) - EPS:
            return p.clip_id, p.src_start + max(0.0, t - p.out_start)
    last = pieces[-1]
    return last.clip_id, last.src_end


def subtitle_edited_span(clips, sub: Subtitle) -> tuple[float, float] | None:
    clip = next((c for c in clips if c.id == sub.clip_id), None)
    if clip is None:
        return None
    keeps = enabled_keeps(clip)
    start = next((max(sub.src_start, k.start) for k in keeps if k.end > sub.src_start + EPS), None)
    end = next((min(sub.src_end, k.end) for k in reversed(keeps) if k.start < sub.src_end - EPS), None)
    if start is None or end is None or end - start <= EPS:
        return None
    es, ee = source_to_edited(clips, clip.id, start), source_to_edited(clips, clip.id, end)
    if es is None or ee is None or ee - es <= EPS:
        return None
    return es, ee


def subtitles_for_export(clips, subs, sel: Selection) -> list[tuple[float, float, Subtitle]]:
    out = []
    for s in subs:
        span = subtitle_edited_span(clips, s)
        if span is None:
            continue
        a, b = max(span[0], sel.start), min(span[1], sel.end)
        if b - a > EPS:
            out.append((a - sel.start, b - sel.start, s))
    return sorted(out, key=lambda x: x[0])
