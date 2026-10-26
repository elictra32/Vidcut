"""Dead-air detection with ffmpeg silencedetect, and conversion of silences to keeps."""
import re

from core.media import NoAudioError, probe, run_ffmpeg
from core.models import Keep

_START = re.compile(r"silence_start:\s*(-?[\d.]+)")
_END = re.compile(r"silence_end:\s*(-?[\d.]+)")


def parse_silencedetect(stderr: str, duration: float) -> list[tuple[float, float]]:
    out, start = [], None
    for line in stderr.splitlines():
        m = _START.search(line)
        if m:
            start = max(0.0, float(m.group(1)))
            continue
        m = _END.search(line)
        if m and start is not None:
            out.append((start, min(duration, float(m.group(1)))))
            start = None
    if start is not None and start < duration:
        out.append((start, duration))
    return out


def detect_silences(path: str, duration: float, noise_db: float = -35.0, min_silence: float = 0.6,
                    progress_cb=None, cancel_event=None) -> list[tuple[float, float]]:
    if not probe(path)["has_audio"]:
        raise NoAudioError(path)
    stderr = run_ffmpeg(["-i", path, "-vn", "-ac", "1", "-ar", "16000",
                         "-af", f"silencedetect=noise={noise_db}dB:d={min_silence}", "-f", "null", "-"],
                        duration, progress_cb, cancel_event)
    return parse_silencedetect(stderr, duration)


def keeps_from_silences(silences, duration: float, padding: float = 0.15,
                        min_keep: float = 0.2) -> list[Keep]:
    """Complement of the silences, after shrinking each silence by `padding` on the sides
    that touch speech (a silence at 0 or at `duration` only shrinks on its inner side)."""
    gaps = []
    for s, e in sorted(silences):
        s2 = s if s <= 1e-6 else s + padding
        e2 = e if e >= duration - 1e-6 else e - padding
        if e2 > s2:
            gaps.append((s2, e2))
    keeps, t = [], 0.0
    for s, e in gaps:
        if s - t >= min_keep:
            keeps.append(Keep(t, s))
        t = max(t, e)
    if duration - t >= min_keep:
        keeps.append(Keep(t, duration))
    return keeps
