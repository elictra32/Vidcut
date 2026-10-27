import os

import pytest

from core.export import ExportResult
from core.models import Clip, Keep, Project
from core.sizing import SAFETY, measure, measure_kbps, sample_windows


def fake_run(sizes_kb):
    """A stand-in for run_export: writes a file of the next size (in kilobytes) for each sample."""
    it = iter(sizes_kb)

    def run(project, out_dir, progress, cancel, **kw):
        path = os.path.join(out_dir, f"s{kw['selection'].start:.0f}.mp4")
        with open(path, "wb") as f:
            f.write(b"0" * int(next(it) * 1000))
        assert kw["intro_ids"] == [] and kw["with_extras"] is False   # samples are the main footage only
        return ExportResult(path, None)
    return run


def project():
    return Project(clips=[Clip("c", "/a.mp4", 600, 10, 10, 25, True, keeps=[Keep(0, 600)])])


def test_the_plan_uses_the_mean_of_the_samples_not_the_busiest_one():
    # 8 s samples of 300, 320, 1400 and 330 kB: one busy moment among calm ones
    m = measure(project(), 0, 600, run=fake_run([300, 320, 1400, 330]))
    rates = [round(kb - 160) for kb in (300, 320, 1400, 330)]   # kB*8 = kbit, over 8 s = kbps; minus audio
    assert m.samples == rates and m.error is None
    assert m.kbps == pytest.approx(sum(rates) / 4 * SAFETY, rel=0.02)
    assert m.kbps < max(rates)                                          # a single busy sample does not set the plan


def test_a_failed_measurement_says_why_instead_of_silently_returning_nothing():
    def boom(*a, **k):
        raise RuntimeError("ffmpeg exploded")
    m = measure(project(), 0, 600, run=boom)
    assert m.kbps is None and "RuntimeError: ffmpeg exploded" in m.error
    assert measure_kbps(project(), 0, 600, run=boom) is None
    assert measure(project(), 5, 5).error                                # an empty range can't be sampled


def test_samples_are_removed_afterwards(tmp_path, monkeypatch):
    import tempfile
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    measure(project(), 0, 600, run=fake_run([10, 10, 10, 10]))
    assert [p for p in os.listdir(tmp_path) if p.startswith("vidcut_size_")] == []


def test_windows_are_still_spread_over_the_range():
    assert len(sample_windows(0, 600)) == 4
