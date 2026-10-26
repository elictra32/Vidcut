import pytest

from core import silence, waveform
from core.media import NoAudioError
from tests.helpers import make_clip

SPEC = [("tone", 1), ("silence", 2), ("tone", 1), ("silence", 1.5)]

STDERR = """
[silencedetect @ 0x1] silence_start: 1.002
[silencedetect @ 0x1] silence_end: 3.001 | silence_duration: 1.999
[silencedetect @ 0x1] silence_start: 4.0
"""


def test_parse_silencedetect_pairs():
    got = silence.parse_silencedetect(STDERR, 5.5)
    assert got[0] == pytest.approx((1.002, 3.001))


def test_parse_trailing_silence_ends_at_duration():
    got = silence.parse_silencedetect(STDERR, 5.5)
    assert got[1] == pytest.approx((4.0, 5.5))


def test_keeps_from_silences_padding():
    keeps = silence.keeps_from_silences([(1, 3), (4, 5.5)], 5.5, padding=0.15)
    assert [(k.start, k.end) for k in keeps] == [pytest.approx((0, 1.15)), pytest.approx((2.85, 4.15))]
    assert all(k.enabled for k in keeps)


def test_keeps_from_silences_leading_silence_shrinks_inner_side_only():
    keeps = silence.keeps_from_silences([(0, 2)], 5, padding=0.15)
    assert [(k.start, k.end) for k in keeps] == [pytest.approx((1.85, 5))]


def test_keeps_from_silences_drops_tiny_keeps():
    keeps = silence.keeps_from_silences([(0, 2), (2.05, 5)], 5, padding=0.0, min_keep=0.2)
    assert keeps == []


def test_detect_silences_on_synthetic_clip(tmp_path):
    p = make_clip(str(tmp_path / "s.mp4"), SPEC)
    got = silence.detect_silences(p, 5.5)
    assert len(got) == 2
    assert got[0] == pytest.approx((1, 3), abs=0.06)
    assert got[1] == pytest.approx((4, 5.5), abs=0.06)
    keeps = silence.keeps_from_silences(got, 5.5)
    assert [(k.start, k.end) for k in keeps] == [pytest.approx((0, 1.15), abs=0.06),
                                                 pytest.approx((2.85, 4.15), abs=0.06)]


def test_detect_silences_no_audio_raises_NoAudioError(tmp_path):
    p = make_clip(str(tmp_path / "n.mp4"), [("tone", 1)], with_audio=False)
    with pytest.raises(NoAudioError):
        silence.detect_silences(p, 1.0)


def test_waveform_peaks_length_and_range(tmp_path):
    p = make_clip(str(tmp_path / "w.mp4"), SPEC)
    peaks = waveform.waveform_peaks(p, n=100)
    assert len(peaks) == 100
    assert all(0.0 <= v <= 1.0 for v in peaks)
    assert max(peaks[:15]) > 0.3 and max(peaks[25:50]) < 0.05
