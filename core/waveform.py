"""Peak envelope of a clip's audio, normalized to the loudest bucket, for drawing the timeline."""
import subprocess

import numpy as np

from core.media import find_ffmpeg, no_window, probe


def waveform_peaks(path: str, n: int = 2000) -> list[float]:
    if not probe(path)["has_audio"]:
        return [0.0] * n
    ffmpeg, _ = find_ffmpeg()
    raw = subprocess.run([ffmpeg, "-hide_banner", "-nostdin", "-i", path, "-vn", "-ac", "1",
                          "-ar", "8000", "-f", "s16le", "-"], capture_output=True, **no_window()).stdout
    samples = np.abs(np.frombuffer(raw, dtype=np.int16).astype(np.float32)) / 32768.0
    if samples.size == 0:
        return [0.0] * n
    peaks = np.array([b.max() if b.size else 0.0 for b in np.array_split(samples, n)])
    top = peaks.max()
    return (peaks / top).tolist() if top > 0 else peaks.tolist()


def loudness_by_second(path: str) -> list[float]:
    """Average loudness (RMS) of each second of the clip's audio; [] when there is no audio."""
    if not probe(path)["has_audio"]:
        return []
    ffmpeg, _ = find_ffmpeg()
    raw = subprocess.run([ffmpeg, "-hide_banner", "-nostdin", "-i", path, "-vn", "-ac", "1",
                          "-ar", "8000", "-f", "s16le", "-"], capture_output=True, **no_window()).stdout
    x = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    n = x.size // 8000
    if n == 0:
        return []
    return np.sqrt((x[: n * 8000].reshape(n, 8000) ** 2).mean(axis=1)).tolist()
