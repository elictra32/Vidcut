"""Per-platform export presets. Line widths are starting values; tune after real use."""
from dataclasses import dataclass, field


@dataclass
class Preset:
    name: str
    width: int
    height: int
    line_width: int
    max_lines: int
    style_overrides: dict = field(default_factory=dict)
    safe_zone: dict = field(default_factory=dict)  # fractions of the frame kept clear of app UI


PRESETS: dict[str, Preset] = {
    "tiktok": Preset("tiktok", 1080, 1920, line_width=14, max_lines=2,
                     style_overrides={"size": 72, "default_y": 0.70},
                     safe_zone={"top": 0.10, "bottom": 0.20, "left": 0.06, "right": 0.15}),
    "youtube": Preset("youtube", 1920, 1080, line_width=36, max_lines=2,
                      style_overrides={"size": 48, "default_y": 0.88},
                      safe_zone={"top": 0.05, "bottom": 0.08, "left": 0.05, "right": 0.05}),
}
