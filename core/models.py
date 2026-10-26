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


@dataclass
class Selection:
    start: float
    end: float


DEFAULT_PRESET = "tiktok"


def _default_style() -> SubtitleStyle:
    """A new project starts with its default preset's subtitle style, not the generic one."""
    return SubtitleStyle(**PRESETS[DEFAULT_PRESET].style_overrides)


@dataclass
class Project:
    clips: list[Clip] = field(default_factory=list)
    selection: Selection | None = None
    subtitles: list[Subtitle] = field(default_factory=list)
    style: SubtitleStyle = field(default_factory=_default_style)
    preset: str = DEFAULT_PRESET


def project_to_dict(p: Project) -> dict:
    return asdict(p)


def project_from_dict(d: dict) -> Project:
    clips = []
    for c in d.get("clips", []):
        c = dict(c)
        c["keeps"] = [Keep(**k) for k in c.get("keeps", [])]
        c["framing"] = Framing(**c.get("framing", {}))
        clips.append(Clip(**c))
    sel = d.get("selection")
    return Project(
        clips=clips,
        selection=Selection(**sel) if sel else None,
        subtitles=[Subtitle(**s) for s in d.get("subtitles", [])],
        style=SubtitleStyle(**d.get("style", {})),
        preset=d.get("preset", "tiktok"),
    )
