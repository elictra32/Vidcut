"""Mapping times of an ORIGINAL video onto a version of it that was cut (dead air removed): a list of pieces, each
saying "original seconds [src_start, src_end) are at out_start.. in the cut video"."""
from dataclasses import dataclass


@dataclass
class CutPiece:
    src_start: float  # in the original
    src_end: float
    out_start: float  # in the cut video

    @property
    def out_end(self) -> float:
        return self.out_start + (self.src_end - self.src_start)


def pieces_from_dicts(items) -> list[CutPiece]:
    out = []
    for d in items or []:
        p = CutPiece(float(d["src_start"]), float(d["src_end"]), float(d["out_start"]))
        if p.src_end > p.src_start:
            out.append(p)
    return sorted(out, key=lambda p: p.src_start)


def map_window(pieces: list[CutPiece], a: float, b: float) -> tuple[float, float] | None:
    """The part of [a, b) that survives in the cut video, in cut-video time. A window that spans a cut keeps the
    part inside the piece it overlaps most. None when it was cut away entirely."""
    best, best_ov = None, 0.0
    for p in pieces:
        lo, hi = max(a, p.src_start), min(b, p.src_end)
        if hi - lo > best_ov:
            best, best_ov = (p.out_start + lo - p.src_start, p.out_start + hi - p.src_start), hi - lo
    return best if best_ov > 0.01 else None
