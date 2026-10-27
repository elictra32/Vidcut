"""Project data model. Everything is a plain dataclass so it round-trips through JSON."""
from dataclasses import dataclass, field, asdict

from core.presets import PRESETS


@dataclass
class Keep:
    start: float
    end: float
    enabled: bool = True


@dataclass
class Framing:
    mode: str = "blur_fit"  # "crop" | "blur_fit"
    crop_center_x: float = 0.5


@dataclass
class Grade:
    """Colour correction of one clip, each from -100 to 100 (0 = untouched). See core/grade.py."""
    temperature: float = 0.0  # + warmer (more yellow/orange), - cooler (bluer)
    tint: float = 0.0         # + towards magenta, - towards green
    brightness: float = 0.0
    contrast: float = 0.0
    saturation: float = 0.0


ROLES = ("main", "intro", "outro")  # intro/outro clips are not on the edit timeline; export joins them around the selection


@dataclass
class Clip:
    id: str
    path: str
    duration: float
    width: int
    height: int
    fps: float
    has_audio: bool
    proxy_path: str | None = None
    keeps: list[Keep] = field(default_factory=list)
    framing: Framing = field(default_factory=Framing)
    grade: Grade = field(default_factory=Grade)
    role: str = "main"
    color_matrix: str = ""    # bt709 / bt601 / bt2020 as probed ("" = not probed: guess from the height)
    full_range: bool = False  # full-range (JPEG-style) YUV instead of the usual limited range
    cuts_confirmed: bool = False  # the user accepted the dead-air cuts; the review strip is tucked away


@dataclass
class Subtitle:
    """Anchored to source time; edited time is always derived (see core/timeline.py)."""
    id: str
    clip_id: str
    src_start: float
    src_end: float
    text: str
    x: float | None = None
    y: float | None = None
    scale: float | None = None  # size multiplier for this line only (None = the style size)


@dataclass
class SubtitleStyle:
    font: str = "Sarabun"
    size: int = 64
    color: str = "#FFFFFF"
    outline_color: str = "#000000"
    outline_width: int = 4
    shadow: int = 0
    bg_color: str | None = None
    default_x: float = 0.5
    default_y: float = 0.78
    align: str = "center"
    reveal: bool = False  # text appears as it is spoken


@dataclass
class Overlay:
    """A logo/photo laid over the video. x,y = centre as fractions of the frame; width = fraction of the frame
    width; start/end are seconds in the EXPORTED file (None = the whole video)."""
    id: str
    path: str
    x: float = 0.88
    y: float = 0.1
    width: float = 0.2
    opacity: float = 1.0
    start: float | None = None
    end: float | None = None


@dataclass
class Selection:
    start: float
    end: float


DEFAULT_PRESET = "tiktok"


def _default_style() -> SubtitleStyle:
    """A new project starts with its default preset's subtitle style, not the generic one."""
    return SubtitleStyle(**PRESETS[DEFAULT_PRESET].style_overrides)


@dataclass
class ExportSettings:
    container: str = "mp4"  # mp4 | mov | mkv | webm
    quality: str = "auto"  # auto | high | medium | small | custom (auto = constant quality, capped; custom uses target_mb)
    target_mb: float | None = None
    out_dir: str = ""  # "" = the default exports folder; set by the server only
    filename: str = ""  # "" = automatic (source name + preset); otherwise the name to give the file (no extension)


@dataclass
class Project:
    clips: list[Clip] = field(default_factory=list)
    selection: Selection | None = None
    subtitles: list[Subtitle] = field(default_factory=list)
    style: SubtitleStyle = field(default_factory=_default_style)
    preset: str = DEFAULT_PRESET
    export: ExportSettings = field(default_factory=ExportSettings)
    overlays: list[Overlay] = field(default_factory=list)
    rev: int = 0  # bumped whenever the server itself changes the project (jobs); stale saves are refused


def project_to_dict(p: Project) -> dict:
    return asdict(p)


def project_from_dict(d: dict) -> Project:
    clips = []
    for c in d.get("clips", []):
        c = dict(c)
        c["keeps"] = [Keep(**k) for k in c.get("keeps", [])]
        c["framing"] = Framing(**c.get("framing", {}))
        c["grade"] = Grade(**c.get("grade", {}))
        clips.append(Clip(**c))
    sel = d.get("selection")
    return Project(
        clips=clips,
        selection=Selection(**sel) if sel else None,
        subtitles=[Subtitle(**s) for s in d.get("subtitles", [])],
        style=SubtitleStyle(**d.get("style", {})),
        preset=d.get("preset", "tiktok"),
        export=ExportSettings(**d.get("export", {})),
        overlays=[Overlay(**o) for o in d.get("overlays", [])],
        rev=int(d.get("rev", 0)),
    )
