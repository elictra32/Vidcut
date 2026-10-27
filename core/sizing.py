"""Measure how many bits a project's footage really needs at the chosen quality, by encoding a few short samples.
Constant-quality (CRF) encoding of easy footage lands far below the worst-case bitrate cap, so planning from the cap
(core/episodes.py without a measurement) splits into more episodes than the size limit requires."""
import os
import shutil
import tempfile

from core.encode import AUDIO_KBPS, _normalized
from core.export import run_export
from core.media import Cancelled
from core.models import Project, Selection

SAMPLES = 4
SAMPLE_S = 8.0
SAFETY = 1.1  # footage varies: plan with a margin over the samples (the encoder cap is the hard guard)


def sample_windows(start: float, end: float, n: int = SAMPLES, length: float = SAMPLE_S) -> list[tuple[float, float]]:
    """`n` windows of `length` seconds spread evenly over [start, end] (fewer, or shorter, for a short range)."""
    total = end - start
    if total <= 0:
        return []
    length = min(length, total)
    n = max(1, min(n, int(total // length)))
    if n == 1:
        a = start + (total - length) / 2
        return [(a, a + length)]
    return [(a, a + length) for a in (start + (total - length) * i / (n - 1) for i in range(n))]


def measure_kbps(project: Project, start: float, end: float, cancel=None, progress=None, run=run_export) -> float | None:
    """Typical video kbps (with a safety margin), from short encodes of the project's own footage with its own export
    settings. None when nothing could be measured."""
    windows = sample_windows(start, end)
    if not windows:
        return None
    audio = AUDIO_KBPS[_normalized(project.export).container]
    scratch = tempfile.mkdtemp(prefix="vidcut_size_")
    rates = []
    try:
        for i, (a, b) in enumerate(windows):
            if cancel is not None and cancel.is_set():
                raise Cancelled()
            if progress:
                progress(i / len(windows), f"Measuring sample {i + 1}/{len(windows)}")
            res = run(project, scratch, None, cancel, selection=Selection(a, b), intro_ids=[], with_extras=False)
            kbits = os.path.getsize(res.video) * 8 / 1000
            rates.append(max(0.0, kbits / (b - a) - audio))
            os.remove(res.video)
    except Cancelled:
        raise
    except Exception:  # noqa: BLE001 - a failed measurement just means "plan from the cap"
        return None
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    if not rates:
        return None
    return (0.5 * sum(rates) / len(rates) + 0.5 * max(rates)) * SAFETY
