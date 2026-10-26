"""ffmpeg/ffprobe helpers: locating binaries, probing, proxies, and a cancellable runner."""
import json
import os
import shutil
import subprocess
import threading


class Cancelled(Exception):
    pass


class NoAudioError(Exception):
    pass


class FFmpegError(Exception):
    def __init__(self, message, details=""):
        super().__init__(message)
        self.details = details


def find_ffmpeg() -> tuple[str, str]:
    ff, fp = shutil.which("ffmpeg"), shutil.which("ffprobe")
    if not ff or not fp:
        raise FileNotFoundError("ffmpeg/ffprobe not found on PATH")
    return ff, fp


def probe(path: str) -> dict:
    _, ffprobe = find_ffmpeg()
    r = subprocess.run([ffprobe, "-v", "error", "-print_format", "json", "-show_streams",
                        "-show_format", path], capture_output=True, text=True, encoding="utf-8")
    if r.returncode != 0:
        raise FFmpegError("probe failed", r.stderr[-2000:])
    data = json.loads(r.stdout)
    streams = data.get("streams", [])
    v = next((s for s in streams if s.get("codec_type") == "video"), None)
    a = next((s for s in streams if s.get("codec_type") == "audio"), None)
    if v is None:
        raise FFmpegError("no video stream")
    w, h = int(v["width"]), int(v["height"])
    if abs(_rotation(v)) % 180 == 90:
        w, h = h, w
    num, _, den = v.get("avg_frame_rate", "0/1").partition("/")
    fps = float(num) / float(den) if den and float(den) else 0.0
    duration = float(data.get("format", {}).get("duration") or v.get("duration") or 0)
    return {
        "duration": duration, "width": w, "height": h, "fps": fps,
        "has_audio": a is not None,
        "vcodec": v.get("codec_name"), "acodec": a.get("codec_name") if a else None,
        "container": data.get("format", {}).get("format_name", ""),
    }


def _rotation(stream: dict) -> int:
    for sd in stream.get("side_data_list", []) or []:
        if "rotation" in sd:
            return int(float(sd["rotation"]))
    return int(stream.get("tags", {}).get("rotate", 0) or 0)


def is_browser_playable(info: dict) -> bool:
    """True when a browser's <video> can play the file as-is (so no proxy is needed)."""
    container, v, a = info.get("container", ""), info.get("vcodec"), info.get("acodec")
    if "mp4" in container:
        return v == "h264" and a in ("aac", "mp3", None)
    if "webm" in container:  # ffprobe reports "matroska,webm" for both; the codecs decide
        return v in ("vp8", "vp9", "av1") and a in ("opus", "vorbis", None)
    return False


def run_ffmpeg(args: list[str], duration: float = 0.0, progress_cb=None, cancel_event=None,
               cwd: str | None = None) -> str:
    """Run ffmpeg with -progress on stdout. Returns stderr. Raises Cancelled / FFmpegError."""
    ffmpeg, _ = find_ffmpeg()
    cmd = [ffmpeg, "-hide_banner", "-nostdin", "-y", "-progress", "pipe:1", "-nostats"] + args
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=cwd,
                            text=True, encoding="utf-8", errors="replace")
    err_chunks: list[str] = []
    t = threading.Thread(target=lambda: err_chunks.append(proc.stderr.read()), daemon=True)
    t.start()
    for line in proc.stdout:
        if cancel_event is not None and cancel_event.is_set():
            proc.kill()
            proc.wait()
            raise Cancelled()
        if progress_cb and duration > 0 and line.startswith("out_time_us="):
            try:
                us = int(line.split("=", 1)[1])
                progress_cb(min(1.0, us / 1e6 / duration), "")
            except ValueError:
                pass
    proc.wait()
    t.join()
    stderr = "".join(err_chunks)
    if cancel_event is not None and cancel_event.is_set():
        raise Cancelled()
    if proc.returncode != 0:
        raise FFmpegError("ffmpeg failed", stderr[-3000:])
    return stderr


def make_proxy(path: str, out_path: str, progress_cb=None, cancel_event=None) -> None:
    info = probe(path)
    tmp = out_path + ".part.mp4"
    try:
        run_ffmpeg(["-i", path, "-vf", "scale=-2:480", "-c:v", "libx264", "-preset", "ultrafast",
                    "-crf", "28", "-c:a", "aac", "-b:a", "96k", "-movflags", "+faststart", tmp],
                   info["duration"], progress_cb, cancel_event)
        os.replace(tmp, out_path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
