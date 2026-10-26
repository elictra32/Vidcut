"""Synthetic media for tests: tone/silence clips generated with ffmpeg."""
import os
import shutil
import subprocess


def _run(args):
    subprocess.run(args, check=True, capture_output=True)


def make_clip(path, seconds_spec, size="640x360", with_audio=True, rotate=0, vcodec="libx264"):
    """Create a clip whose audio follows seconds_spec: [("tone"|"silence", seconds), ...]."""
    total = sum(s for _, s in seconds_spec)
    tmp = path + ".tmp.mp4" if rotate else path
    args = ["ffmpeg", "-y", "-hide_banner", "-f", "lavfi", "-i",
            f"testsrc=size={size}:rate=25:duration={total}"]
    if with_audio:
        parts = []
        for i, (kind, secs) in enumerate(seconds_spec):
            vol = "1" if kind == "tone" else "0"
            parts.append(f"sine=frequency=440:sample_rate=48000:duration={secs},volume={vol}[a{i}]")
        joined = "".join(f"[a{i}]" for i in range(len(seconds_spec)))
        graph = ";".join(parts) + f";{joined}concat=n={len(seconds_spec)}:v=0:a=1[aout]"
        args += ["-filter_complex", graph, "-map", "0:v", "-map", "[aout]", "-c:a", "aac"]
    args += ["-c:v", vcodec, "-pix_fmt", "yuv420p", "-t", str(total), tmp]
    _run(args)
    if rotate:
        _run(["ffmpeg", "-y", "-hide_banner", "-display_rotation", str(rotate), "-i", tmp,
              "-c", "copy", path])
        os.remove(tmp)
    return path


def has_libass():
    out = subprocess.run(["ffmpeg", "-hide_banner", "-filters"], capture_output=True, text=True).stdout
    return " subtitles " in out and shutil.which("ffmpeg") is not None
