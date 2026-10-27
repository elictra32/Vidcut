"""Subtitle output: ASS (burned in by libass at export) and SRT (sidecar file).
The style -> CSS mapping is `style()` in web/stage.js; keep it in step with _style_line.
style.size is the CSS em size in output pixels; core/fonts.py converts it to libass Fontsize."""
from dataclasses import dataclass

from core.fonts import ass_size_factor
from core.models import SubtitleStyle


@dataclass
class RenderedSub:
    start: float  # seconds, relative to the exported output
    end: float
    text: str
    x: float | None
    y: float | None
    scale: float | None = None


def _ass_color(hex_color: str, alpha: int = 0) -> str:
    h = hex_color.lstrip("#")
    r, g, b = h[0:2], h[2:4], h[4:6]
    return f"&H{alpha:02X}{b}{g}{r}".upper()


def _ass_time(t: float) -> str:
    cs = int(round(max(0.0, t) * 100))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _escape(text: str) -> str:
    return (text.replace("\\", "＼").replace("{", "｛").replace("}", "｝")
            .replace("\n", "\\N"))


def _style_line(style: SubtitleStyle) -> str:
    box = style.bg_color is not None
    outline_color = _ass_color(style.bg_color) if box else _ass_color(style.outline_color)
    border_style = 3 if box else 1
    return ("Style: Default," + ",".join(str(v) for v in [
        style.font, round(style.size * ass_size_factor(style.font)), _ass_color(style.color), _ass_color(style.color),
        outline_color, _ass_color("#000000", 0x80),
        0, 0, 0, 0, 100, 100, 0, 0, border_style, style.outline_width, style.shadow,
        5, 0, 0, 0, 1]))


def to_ass(subs: list[RenderedSub], style: SubtitleStyle, play_res: tuple[int, int]) -> str:
    w, h = play_res
    lines = [
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {w}", f"PlayResY: {h}",
        "WrapStyle: 2", "ScaledBorderAndShadow: yes", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
        "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
        "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        _style_line(style), "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    for s in subs:
        x = round((s.x if s.x is not None else style.default_x) * w)
        y = round((s.y if s.y is not None else style.default_y) * h)
        zoom = f"\\fscx{round(s.scale * 100)}\\fscy{round(s.scale * 100)}" if s.scale and abs(s.scale - 1) > 0.005 else ""
        lines.append(f"Dialogue: 0,{_ass_time(s.start)},{_ass_time(s.end)},Default,,0,0,0,,"
                     f"{{\\an5\\pos({x},{y}){zoom}}}{_escape(s.text)}")
    return "\n".join(lines) + "\n"


def _srt_time(t: float) -> str:
    ms = int(round(max(0.0, t) * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def to_srt(subs: list[RenderedSub]) -> str:
    blocks = [f"{i}\n{_srt_time(s.start)} --> {_srt_time(s.end)}\n{s.text}\n"
              for i, s in enumerate(subs, 1)]
    return "\n".join(blocks)
