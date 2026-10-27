"""Find which parts of an ORIGINAL video a cut version contains, by comparing their audio. Works for a video cut in
any program, as long as it only removed stretches (dead air) and kept the rest in order.

Each file becomes a sequence of small spectral "shapes" (one per 50 ms). Windows of the cut video are searched for in
the original by normalised cross-correlation; the sequence of matches is made consistent (offsets can only grow, since
material is only removed) and the exact cut points are refined frame by frame."""
import subprocess
from dataclasses import dataclass

import numpy as np

from core.cutmap import CutPiece
from core.media import Cancelled, find_ffmpeg, no_window

RATE = 8000
HOP_S = 0.05
HOP = int(RATE * HOP_S)
N_FFT = 512
BANDS = 12
WINDOW_FRAMES = 200   # 10 s
STRIDE_FRAMES = 100   # 5 s
MIN_NCC = 0.5
MIN_MARGIN = 0.15  # the best match must stand clear of the next best place, or it may be a coincidence
GROUP_TOL_S = 0.15
SILENT = 1e-7
EDGE_PAD = 50  # frames (2.5 s)


@dataclass
class AlignResult:
    pieces: list[CutPiece]
    coverage: float    # share of the cut video that was matched to the original
    confidence: float  # mean correlation of the matched windows


def decode(path: str, cancel=None) -> np.ndarray:
    ffmpeg, _ = find_ffmpeg()
    raw = subprocess.run([ffmpeg, "-hide_banner", "-nostdin", "-i", path, "-vn", "-ac", "1", "-ar", str(RATE), "-f", "s16le", "-"],
                         capture_output=True, **no_window()).stdout
    if cancel is not None and cancel.is_set():
        raise Cancelled()
    return np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0


def features(x: np.ndarray) -> np.ndarray:
    """(frames, BANDS) loudness-independent spectral shapes; silent frames are all zero."""
    n = (len(x) - N_FFT) // HOP + 1
    if n <= 0:
        return np.zeros((0, BANDS), dtype=np.float32)
    freqs = np.fft.rfftfreq(N_FFT, 1 / RATE)
    edges = np.geomspace(150, 3800, BANDS + 1)
    masks = [(freqs >= lo) & (freqs < hi) for lo, hi in zip(edges[:-1], edges[1:])]
    win = np.hanning(N_FFT).astype(np.float32)
    chunks = []
    for c0 in range(0, n, 20000):  # in pieces: an hour of audio would otherwise need hundreds of MB at once
        c1 = min(n, c0 + 20000)
        idx = np.arange(N_FFT)[None, :] + HOP * np.arange(c0, c1)[:, None]
        spec = np.abs(np.fft.rfft(x[idx] * win, axis=1)) ** 2
        chunks.append(np.stack([spec[:, m].sum(axis=1) for m in masks], axis=1))
    bands = np.concatenate(chunks)
    loud = bands.sum(axis=1)
    f = np.log(bands + 1e-9)
    f -= f.mean(axis=1, keepdims=True)
    silent = loud < SILENT * N_FFT
    if (~silent).any():
        f -= f[~silent].mean(axis=0, keepdims=True)  # the file's average shape: what all speech has in common
    f[silent] = 0.0
    return f.astype(np.float32)


class _Searcher:
    def __init__(self, orig: np.ndarray):
        self.n = orig.shape[0]
        self.size = 1 << int(np.ceil(np.log2(self.n + WINDOW_FRAMES + 1)))
        self.spec = np.fft.rfft(orig.T, self.size, axis=1)
        self.cum = np.concatenate([[0.0], np.cumsum((orig ** 2).sum(axis=1))])

    def best(self, q: np.ndarray) -> tuple[int, float, float]:
        L = q.shape[0]
        qs = np.fft.rfft(q.T, self.size, axis=1)
        corr = np.fft.irfft((self.spec * np.conj(qs)).sum(axis=0), self.size)[: self.n - L + 1]
        energy = np.sqrt(np.maximum(self.cum[L:] - self.cum[: self.n - L + 1], 1e-9))
        ncc = corr / (np.linalg.norm(q) * energy + 1e-9)
        t = int(np.argmax(ncc))
        rest = ncc.copy()
        rest[max(0, t - 40): t + 40] = -1.0
        return t, float(ncc[t]), float(ncc[t] - rest.max())


def _longest_nondecreasing(values: list[int]) -> list[int]:
    """Indices of a longest non-decreasing subsequence."""
    import bisect
    tails, tail_idx, prev = [], [], [-1] * len(values)
    for i, v in enumerate(values):
        k = bisect.bisect_right(tails, v)
        if k == len(tails):
            tails.append(v)
            tail_idx.append(i)
        else:
            tails[k], tail_idx[k] = v, i
        prev[i] = tail_idx[k - 1] if k else -1
    out, i = [], tail_idx[-1] if tail_idx else -1
    while i >= 0:
        out.append(i)
        i = prev[i]
    return out[::-1]


def _distance(cut: np.ndarray, orig: np.ndarray, shift: int, lo: int, hi: int) -> np.ndarray:
    """Per-frame mismatch (1 - cosine) of cut frames lo..hi against the original `shift` frames later."""
    out = np.ones(hi - lo)
    for k, t in enumerate(range(lo, hi)):
        j = t + shift
        if 0 <= j < orig.shape[0]:
            a, b = cut[t], orig[j]
            na, nb = np.linalg.norm(a), np.linalg.norm(b)
            out[k] = 1.0 - float(a @ b) / (na * nb) if na > 0 and nb > 0 else 0.5
    return out


def _change_point(cut, orig, shift_a, shift_b, lo, hi) -> int:
    """Frame in [lo, hi] where the cut video switches from original offset A to offset B."""
    if hi <= lo:
        return lo
    ea, eb = _distance(cut, orig, shift_a, lo, hi), _distance(cut, orig, shift_b, lo, hi)
    # cost of switching at lo+k: errors under A before it plus errors under B from it on
    cost = np.concatenate([[0.0], np.cumsum(ea)]) + (eb.sum() - np.concatenate([[0.0], np.cumsum(eb)]))
    return lo + int(np.argmin(cost))


def align(cut_path: str, original_path: str, progress=None, cancel=None) -> AlignResult:
    report = progress or (lambda f, m="": None)
    report(0.0, "Reading the audio of both files")
    cut_f = features(decode(cut_path, cancel))
    report(0.15, "Reading the audio of both files")
    orig_f = features(decode(original_path, cancel))
    return align_features(cut_f, orig_f, report, cancel)


def align_features(cut: np.ndarray, orig: np.ndarray, report=None, cancel=None) -> AlignResult:
    report = report or (lambda f, m="": None)
    total = cut.shape[0]
    if total < WINDOW_FRAMES or orig.shape[0] < WINDOW_FRAMES:
        return AlignResult([], 0.0, 0.0)
    starts = list(range(0, total - WINDOW_FRAMES + 1, STRIDE_FRAMES))
    if starts[-1] != total - WINDOW_FRAMES:
        starts.append(total - WINDOW_FRAMES)
    searcher = _Searcher(orig)
    found = []  # (window start, offset in frames, ncc)
    for n, s in enumerate(starts):
        if cancel is not None and cancel.is_set():
            raise Cancelled()
        report(0.2 + 0.7 * n / len(starts), "Matching the cut video against the original")
        q = cut[s: s + WINDOW_FRAMES]
        if np.count_nonzero(np.abs(q).sum(axis=1)) < WINDOW_FRAMES * 0.3:
            continue  # mostly silence: it matches anywhere
        t, ncc, margin = searcher.best(q)
        if ncc >= MIN_NCC and margin >= MIN_MARGIN:
            found.append((s, t - s, ncc))
    if not found:
        return AlignResult([], 0.0, 0.0)
    keep = _longest_nondecreasing([off for _, off, _ in found])
    found = [found[i] for i in keep]
    # group windows whose offsets agree
    tol = int(GROUP_TOL_S / HOP_S)
    groups: list[list[tuple[int, int, float]]] = []
    for w in found:
        if groups and abs(w[1] - groups[-1][-1][1]) <= tol:
            groups[-1].append(w)
        else:
            groups.append([w])
    report(0.92, "Finding the exact cut points")
    bounds = []  # (start frame, end frame, offset frames) in cut time
    for gi, g in enumerate(groups):
        offset = int(np.median([o for _, o, _ in g]))
        a, b = g[0][0], g[-1][0] + WINDOW_FRAMES
        bounds.append([a, b, offset])
    for i in range(len(bounds) - 1):
        A, B = bounds[i], bounds[i + 1]
        # A's windows match up to A's end and B's from B's start; a window that straddles the cut can match either
        # way, so the cut lies somewhere between those two frames, in whichever order they fall
        # (a window that is mostly one side still matches with a bit of the other, hence the padding)
        lo, hi = min(A[1], B[0]) - EDGE_PAD, max(A[1], B[0]) + EDGE_PAD
        cp = _change_point(cut, orig, A[2], B[2], max(A[0], lo), min(B[1], total, hi))
        A[1] = B[0] = cp
    if bounds[0][0] <= STRIDE_FRAMES:
        bounds[0][0] = 0
    if total - bounds[-1][1] <= STRIDE_FRAMES:
        bounds[-1][1] = total
    pieces, matched = [], 0
    for a, b, off in bounds:
        if b <= a:
            continue
        pieces.append(CutPiece((a + off) * HOP_S, (b + off) * HOP_S, a * HOP_S))
        matched += b - a
    conf = float(np.mean([n for _, _, n in found]))
    report(1.0, "Done")
    return AlignResult(pieces, matched / total, conf)
