"""Export file format, quality and size: a fixed video bitrate per quality level (so the size is
predictable before encoding), or a bitrate derived from a target size in MB."""
from core.models import ExportSettings

CONTAINERS = ("mp4", "mov", "mkv", "webm")
QUALITIES = ("auto", "smallest", "high", "medium", "small", "custom")
# video kbps per output frame size: TikTok is 1080x1920, YouTube 1920x1080
QUALITY_KBPS = {
    "tiktok": {"high": 8000, "medium": 5000, "small": 3000},
    "youtube": {"high": 12000, "medium": 8000, "small": 5000},
}
AUDIO_KBPS = {"mp4": 160, "mov": 160, "mkv": 160, "webm": 128}
MIN_VIDEO_KBPS = 300
CONTAINER_OVERHEAD = 1.02  # muxing adds about 2% on top of the streams


def _normalized(s: ExportSettings) -> ExportSettings:
    return ExportSettings(
        container=s.container if s.container in CONTAINERS else "mp4",
        quality=s.quality if s.quality in QUALITIES else "medium",
        target_mb=s.target_mb, out_dir=s.out_dir)


def output_extension(s: ExportSettings) -> str:
    return _normalized(s).container


# A re-encode can't add detail the source never had: spending 8 Mbps on a 1.8 Mbps phone clip only makes
# a bigger file. So each quality level is a share of the source bitrate, capped by the table above.
SOURCE_SHARE = {"auto": 1.2, "smallest": 1.2, "high": 1.2, "medium": 0.8, "small": 0.5}
AUTO_CRF = {"x264": 22, "vp9": 33}  # constant-quality level for "auto": visually close to a decent source
# "smallest": the same idea with a slower, more thorough encoder and one step more compression (about 25-30% less data, no
# visible change on talking-head / slide footage in our checks), at the price of a longer export
SMALLEST_CRF = {"x264": 23, "vp9": 34}
CONSTANT_QUALITY = ("auto", "smallest")


def capped_quality(q: str) -> str:
    """Quality to use when a size limit is set (episodes, highlight clips): constant quality, capped per file."""
    return q if q in CONSTANT_QUALITY else "auto"
MIN_CAPPED_KBPS = 800


def source_video_kbps(clips) -> float | None:
    """Average video bitrate of the clips' files (file size over duration, less a typical audio track)."""
    import os
    size = dur = 0.0
    for c in clips:
        try:
            size += os.path.getsize(c.path)
        except OSError:
            continue
        dur += c.duration
    if dur <= 0 or size <= 0:
        return None
    return max(500.0, size * 8 / dur / 1000 - 128)


def video_kbps(s: ExportSettings, preset_name: str, duration: float, source_kbps: float | None = None) -> int:
    s = _normalized(s)
    table = QUALITY_KBPS.get(preset_name, QUALITY_KBPS["tiktok"])
    if s.quality == "custom" and s.target_mb and duration > 0:
        stream_bytes = s.target_mb * 1048576 / CONTAINER_OVERHEAD
        return max(MIN_VIDEO_KBPS, round(stream_bytes * 8 / duration / 1000 - AUDIO_KBPS[s.container]))
    quality = "medium" if s.quality == "custom" else s.quality
    kbps = table["high" if quality in CONSTANT_QUALITY else quality]
    if source_kbps:
        kbps = min(kbps, max(MIN_CAPPED_KBPS, round(source_kbps * SOURCE_SHARE[quality])))
    return kbps


def estimate_bytes(s: ExportSettings, preset_name: str, duration: float, source_kbps: float | None = None) -> int:
    """Expected size of the file. Exact for a constant bitrate; real encoders land within ~10-15%,
    below the figure for easy footage."""
    if duration <= 0:
        return 0
    s = _normalized(s)
    kbps = video_kbps(s, preset_name, duration, source_kbps) + AUDIO_KBPS[s.container]
    return round(kbps * 1000 / 8 * duration * CONTAINER_OVERHEAD)


def encoder_args(s: ExportSettings, preset_name: str, duration: float, source_kbps: float | None = None,
                 max_kbps: int | None = None) -> list[str]:
    """ffmpeg codec/bitrate/container options for the final file (everything between the maps and the output name)."""
    s = _normalized(s)
    v = video_kbps(s, preset_name, duration, source_kbps)
    if max_kbps:
        v = min(v, max_kbps)
    rate = ["-b:v", f"{v}k", "-maxrate", f"{round(v * 1.25)}k", "-bufsize", f"{v * 2}k"]
    if s.quality in CONSTANT_QUALITY:
        # constant quality: easy footage (a talking head, slides) takes far fewer bits than the cap, which only
        # stops busy scenes from running away.
        crf = (SMALLEST_CRF if s.quality == "smallest" else AUTO_CRF)["vp9" if s.container == "webm" else "x264"]
        rate = ["-crf", str(crf), "-maxrate", f"{v}k", "-bufsize", f"{v * 2}k"]
        if s.container == "webm":
            rate = ["-b:v", f"{v}k", *rate]
    if s.container == "webm":
        return ["-c:v", "libvpx-vp9", *rate, "-deadline", "good", "-cpu-used", "4", "-row-mt", "1", "-pix_fmt", "yuv420p",
                "-c:a", "libopus", "-b:a", f"{AUDIO_KBPS['webm']}k"]
    args = ["-c:v", "libx264", "-preset", "slow" if s.quality == "smallest" else "veryfast", *rate, "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", f"{AUDIO_KBPS[s.container]}k"]
    return args + (["-movflags", "+faststart"] if s.container in ("mp4", "mov") else [])
