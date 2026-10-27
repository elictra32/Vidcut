import wave

import numpy as np
import pytest

from core.align import RATE, align, align_features, features

rng = np.random.default_rng(7)


def speechlike(seconds: float, seed: int) -> np.ndarray:
    """Noise whose spectral shape changes every 0.3 s, like syllables; different for each seed."""
    r = np.random.default_rng(seed)
    out = []
    for _ in range(int(seconds / 0.3)):
        n = int(0.3 * RATE)
        spec = np.fft.rfft(r.standard_normal(n))
        gains = np.interp(np.fft.rfftfreq(n, 1 / RATE), np.linspace(0, 4000, 9), r.uniform(0.05, 1.0, 9))
        out.append(np.fft.irfft(spec * gains, n))
    x = np.concatenate(out)
    return (x / np.abs(x).max() * 0.5).astype(np.float32)


def cut_of(orig: np.ndarray, ranges, gain=0.8, noise=0.002):
    parts = [orig[int(a * RATE): int(b * RATE)] for a, b in ranges]
    x = np.concatenate(parts) * gain
    return (x + rng.standard_normal(x.size).astype(np.float32) * noise).astype(np.float32)


RANGES = [(5.0, 38.0), (52.5, 90.0), (101.0, 140.0), (150.0, 175.0)]


def check(result, ranges):
    assert len(result.pieces) == len(ranges), result.pieces
    out = 0.0
    for p, (a, b) in zip(result.pieces, ranges):
        assert p.src_start == pytest.approx(a, abs=0.2) and p.src_end == pytest.approx(b, abs=0.2)
        assert p.out_start == pytest.approx(out, abs=0.2)
        out += b - a


def test_recovers_every_kept_range_and_its_position():
    orig = speechlike(180, 1)
    result = align_features(features(cut_of(orig, RANGES)), features(orig))
    check(result, RANGES)
    assert result.coverage > 0.95 and result.confidence > 0.8


def test_a_cut_made_with_one_piece_only():
    orig = speechlike(120, 2)
    result = align_features(features(cut_of(orig, [(20.0, 100.0)])), features(orig))
    assert len(result.pieces) == 1 and result.pieces[0].src_start == pytest.approx(20.0, abs=0.2)


def test_an_unrelated_intro_is_left_unmatched():
    orig = speechlike(180, 3)
    intro = speechlike(12, 99)
    cut = np.concatenate([intro, cut_of(orig, RANGES[:2])])
    result = align_features(features(cut), features(orig))
    assert result.coverage < 1.0
    first = result.pieces[0]
    assert first.out_start >= 10.0 and first.src_start == pytest.approx(RANGES[0][0] + (first.out_start - 12.0), abs=0.3)


def test_unrelated_audio_gives_no_pieces():
    result = align_features(features(speechlike(60, 5)), features(speechlike(120, 6)))
    assert result.pieces == [] and result.coverage == 0.0


def write_wav(path, x):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes((np.clip(x, -1, 1) * 32767).astype(np.int16).tobytes())


def test_align_from_files(tmp_path):
    orig = speechlike(180, 4)
    write_wav(tmp_path / "orig.wav", orig)
    write_wav(tmp_path / "cut.wav", cut_of(orig, RANGES))
    result = align(str(tmp_path / "cut.wav"), str(tmp_path / "orig.wav"))
    check(result, RANGES)
