"""Audio overview of a clip, for drawing the timeline and for the highlight scan. The audio is decoded ONCE (the slow
part, about 15 s per 80 minutes) into a fine peak envelope plus loudness per second, and kept on disk so that the next
session, the next scan and the next clip view cost nothing."""
import hashlib
import os
import subprocess

import numpy as np

from core.media import find_ffmpeg, no_window, probe

RATE = 8000
PEAKS_PER_S = 20


def _decode(path: str) -> tuple[np.ndarray, np.ndarray]:
    """(peak per 1/PEAKS_PER_S s, RMS per second) from one pass over the audio; both empty when there is no audio."""
    ffmpeg, _ = find_ffmpeg()
    raw = subprocess.run([ffmpeg, "-hide_banner", "-nostdin", "-i", path, "-map", "0:a:0?", "-vn", "-sn", "-dn", "-ac", "1",
                          "-ar", str(RATE), "-f", "s16le", "-"], capture_output=True, **no_window()).stdout
    x = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    win = RATE // PEAKS_PER_S
    n = x.size // win
    if n == 0:
        return np.zeros(0, np.float32), np.zeros(0, np.float32)
    peaks = np.abs(x[: n * win]).reshape(n, win).max(axis=1)
    secs = x.size // RATE
    loud = np.sqrt((x[: secs * RATE].reshape(secs, RATE) ** 2).mean(axis=1)) if secs else np.zeros(0, np.float32)
    return peaks.astype(np.float32), loud.astype(np.float32)


def audio_profile(path: str, cache_dir: str | None = None) -> tuple[np.ndarray, np.ndarray]:
    """(fine peaks, loudness per second), from the disk cache when this exact file was decoded before."""
    key = None
    if cache_dir:
        st = os.stat(path)
        key = os.path.join(cache_dir, hashlib.sha1(f"{os.path.abspath(path)}|{st.st_size}|{st.st_mtime_ns}".encode()).hexdigest() + ".npz")
        try:
            with np.load(key) as z:
                return z["peaks"], z["loud"]
        except (OSError, ValueError, KeyError):
            pass
    peaks, loud = _decode(path) if probe(path)["has_audio"] else (np.zeros(0, np.float32), np.zeros(0, np.float32))
    if key:
        try:
            os.makedirs(cache_dir, exist_ok=True)
            np.savez(key + ".tmp.npz", peaks=peaks, loud=loud)
            os.replace(key + ".tmp.npz", key)
        except OSError:
            pass  # a read-only cache just means decoding again next time
    return peaks, loud


def waveform_peaks(path: str, n: int = 2000, cache_dir: str | None = None) -> list[float]:
    peaks, _ = audio_profile(path, cache_dir)
    if peaks.size == 0:
        return [0.0] * n
    edges = np.linspace(0, peaks.size, n + 1).astype(int)
    starts = np.minimum(edges[:-1], peaks.size - 1)
    out = np.maximum.reduceat(peaks, starts)
    out[edges[1:] <= edges[:-1]] = 0.0   # more points than data: the empty ones are silent
    top = out.max()
    return (out / top).tolist() if top > 0 else out.tolist()


def loudness_by_second(path: str, cache_dir: str | None = None) -> list[float]:
    """Average loudness (RMS) of each second of the clip's audio; [] when there is no audio."""
    return audio_profile(path, cache_dir)[1].tolist()
