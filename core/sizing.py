"""Measure how many bits a project's footage really needs at the chosen quality, by encoding a few short samples.
Constant-quality (CRF) encoding of easy footage lands far below the worst-case bitrate cap, so planning from the cap
(core/episodes.py without a measurement) splits into more episodes than the size limit requires."""
import os
import shutil
import tempfile
from dataclasses import dataclass, field

from core.encode import AUDIO_KBPS, _normalized
from core.export import run_export
from core.media import Cancelled
from core.models import Project, Selection

SAMPLES = 4
SAMPLE_S = 8.0
SAFETY = 1.15  # footage varies: plan with a margin over the mean of the samples (the encoder cap is the hard guard)


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


@dataclass
class Measurement:
    kbps: float | None = None            # typical video kbps to plan with (mean of the samples plus a margin)
    samples: list[float] = field(default_factory=list)  # video kbps of each sample, for showing the user
    error: str | None = None             # why nothing could be measured


def measure(project: Project, start: float, end: float, cancel=None, progress=None, run=run_export) -> Measurement:
    """Typical video bitrate of the project's own footage at its own export settings, from a few short encodes."""
    windows = sample_windows(start, end)
    if not windows:
        return Measurement(error="The range is too short to sample")
    audio = AUDIO_KBPS[_normalized(project.export).container]
    scratch = tempfile.mkdtemp(prefix="vidcut_size_")
    rates: list[float] = []
    try:
        for i, (a, b) in enumerate(windows):
            if cancel is not None and cancel.is_set():
                raise Cancelled()
            if progress:
                progress(i / len(windows), f"Measuring sample {i + 1}/{len(windows)}")
            res = run(project, scratch, None, cancel, selection=Selection(a, b), intro_ids=[], with_extras=False)
            rates.append(max(0.0, os.path.getsize(res.video) * 8 / 1000 / (b - a) - audio))
            os.remove(res.video)
    except Cancelled:
        raise
    except Exception as e:  # noqa: BLE001 - say why, then the plan falls back to the worst case
        return Measurement(error=f"{type(e).__name__}: {e}"[:300])
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    return Measurement(kbps=sum(rates) / len(rates) * SAFETY, samples=[round(r) for r in rates])


def measure_kbps(project: Project, start: float, end: float, cancel=None, progress=None, run=run_export) -> float | None:
    return measure(project, start, end, cancel, progress, run).kbps
