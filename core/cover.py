"""Episode cover ("ปกหัว") generator for the THUS intro template.

The template is a 3.1 s clip: an animated logo on a dark gradient, then a black box with the episode title in orange,
and below it a LIVE badge with the date. This keeps everything but the two texts: the old text area is filled in from
its surroundings (ffmpeg `delogo`), and the new title and date are laid over it with the same timing (fade in,
slow grow, fade out) that was measured from the sample covers. The LIVE badge is cut out of the template itself."""
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from core import media
from core.fonts import FONT_FILES, FONTS_DIR, ass_size_factor, text_advance
from core.media import Cancelled, FFmpegError, find_ffmpeg

W, H = 1920, 1080
FPS = 30


@dataclass(frozen=True)
class Profile:
    """Where things sit in the template, measured from the sample covers (pixels at 1920x1080, seconds)."""
    clean: tuple = (490, 692, 900, 180)        # x, y, w, h of the area holding the old texts
    title_center: tuple = (936.5, 735.5)
    title_text_dy: float = 2.5                  # the letters sit a little lower in their box than the box centre
    title_color: str = "F5853E"
    title_px: float = 44.0                      # font em size
    box_h: int = 72                             # the black box behind the title
    box_pad_x: float = 33.0                     # space between the text and the box edge, each side
    box_min_w: float = 672.0                    # short titles still get a box at least this wide
    title_spacing: float = 1.5                  # extra space between letters, as in the sample covers
    date_left: float = 806.0
    date_center_y: float = 829.5
    date_px: float = 44.7
    date_color: str = "FFFFFF"
    badge_crop: tuple = (632, 806, 154, 57)     # the LIVE badge as it sits in the template (x, y, w, h)
    badge_at: float = 2.55                      # a moment when it is fully shown
    scale_center: tuple = (935.5, 831.0)        # the texts grow about this point
    scale_from: float = 0.918                   # size at the start of the grow, relative to the end
    grow: tuple = (1.07, 2.67)                  # grow runs between these times
    poster_until: float = 0.5                   # the first frames show the finished cover
    title_in: tuple = (0.97, 0.55)              # start, fade duration
    date_in: tuple = (1.23, 0.37)
    title_out: tuple = (2.67, 0.30)
    date_out: tuple = (2.80, 0.20)
    end: float = 3.1


THUS = Profile()


class CoverError(Exception):
    def __init__(self, code: str, message: str, details: str = ""):
        super().__init__(message)
        self.code, self.message, self.details = code, message, details


def _ass_color(rgb_hex: str) -> str:
    r, g, b = rgb_hex[0:2], rgb_hex[2:4], rgb_hex[4:6]
    return f"&H00{b}{g}{r}".upper()


def _ts(t: float) -> str:
    cs = int(round(t * 100))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _escape(text: str) -> str:
    return text.replace("\\", "＼").replace("{", "｛").replace("}", "｝").replace("\n", " ")


def scale_at(p: Profile, t: float) -> float:
    a, b = p.grow
    return p.scale_from + (1 - p.scale_from) * min(1.0, max(0.0, (t - a) / (b - a)))


def build_ass(p: Profile, title: str, date_text: str, title_font: str, date_font: str) -> str:
    tf, df = ass_size_factor(title_font), ass_size_factor(date_font)
    cx, cy = p.title_center
    sx, sy = p.scale_center
    lines = [
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {W}", f"PlayResY: {H}", "WrapStyle: 2", "ScaledBorderAndShadow: yes", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, "
        "StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: Title,{title_font},{round(p.title_px * tf)},{_ass_color(p.title_color)},&H000000,&H00000000,&H00000000,0,0,0,0,100,100,{p.title_spacing},0,1,"
        f"0,0,5,0,0,0,1",
        f"Style: Date,{date_font},{round(p.date_px * df)},{_ass_color(p.date_color)},&H000000,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,0,0,4,0,0,0,1",
        f"Style: Box,{title_font},20,&H00000000,&H000000,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,0,0,5,0,0,0,1",
        "", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"]
    t_text = _escape(title.strip())
    box_w = max(text_advance(title_font, t_text, p.title_px, p.title_spacing) + 2 * p.box_pad_x, p.box_min_w)
    box = f"m 0 0 l {box_w:.1f} 0 {box_w:.1f} {p.box_h} 0 {p.box_h}"
    d_text = _escape(date_text.strip())

    def ev(style, a, b, tags, text):
        lines.append(f"Dialogue: 0,{_ts(a)},{_ts(b)},{style},,0,0,0,,{{{tags}}}{text}")

    # the finished cover shown at the very start
    ev("Box", 0, p.poster_until, f"\\an5\\pos({cx},{cy})\\1c&H000000&\\bord0\\shad0\\p1", box + "{\\p0}")
    ev("Title", 0, p.poster_until, f"\\pos({cx},{cy + p.title_text_dy})", t_text)
    ev("Date", 0, p.poster_until, f"\\pos({p.date_left},{p.date_center_y})", d_text)
    # fade in while growing, then fade out
    for style, (a0, fin), (o0, fout), text, anchor in (
            ("Title", p.title_in, p.title_out, t_text, None), ("Date", p.date_in, p.date_out, d_text, "left")):
        end = o0 + fout
        s0 = scale_at(p, a0)
        grow_ms = round((min(p.grow[1], end) - a0) * 1000)
        s0p = round(s0 * 100, 1)
        if anchor == "left":
            # the date is anchored at its left edge, so move that edge while the text grows about the shared centre
            x0 = sx + s0 * (p.date_left - sx)
            pos = f"\\move({x0:.1f},{p.date_center_y},{p.date_left},{p.date_center_y},0,{grow_ms})"
        else:
            pos = f"\\pos({cx},{cy + p.title_text_dy})"
        anim = f"\\fscx{s0p}\\fscy{s0p}\\t(0,{grow_ms},\\fscx100\\fscy100)\\fad({round(fin * 1000)},{round(fout * 1000)})"
        if style == "Title":
            ev("Box", a0, end, f"\\an5\\pos({cx},{cy})\\1c&H000000&\\bord0\\shad0\\p1{anim}", box + "{\\p0}")
        ev(style, a0, end, pos + anim, text)
    return "\n".join(lines) + "\n"


def _run(cmd: list[str], cancel=None, cwd: str | None = None) -> None:
    ffmpeg, _ = find_ffmpeg()
    try:
        r = subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-y", *cmd], capture_output=True, text=True, cwd=cwd)
    except FileNotFoundError as e:
        raise CoverError("ffmpeg_missing", "ffmpeg not found. Please run setup.bat again") from e
    if cancel is not None and cancel.is_set():
        raise Cancelled()
    if r.returncode != 0:
        raise CoverError("cover_failed", "Couldn't create the cover", r.stderr[-1500:])


def _key_color(png: str, p: Profile) -> str:
    """The background colour around the badge: the median of the crop's border, as 0xRRGGBB."""
    ffmpeg, _ = find_ffmpeg()
    raw = subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-i", png, "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                         capture_output=True).stdout
    w, h = p.badge_crop[2], p.badge_crop[3]
    img = np.frombuffer(raw, dtype=np.uint8).reshape(h, w, 3)
    ring = np.concatenate([img[0], img[-1], img[:, 0], img[:, -1]])
    r, g, b = (int(v) for v in np.median(ring, axis=0))
    return f"0x{r:02X}{g:02X}{b:02X}"


def check_template(path: str, p: Profile = THUS) -> None:
    try:
        info = media.probe(path)
    except FFmpegError as e:
        raise CoverError("unreadable_media", "The template file is damaged or unreadable", e.details) from e
    if (info["width"], info["height"]) != (W, H) or not (2.5 <= info["duration"] <= 4.0):
        raise CoverError("template_mismatch", "This doesn't look like the THUS cover template",
                         f"Expected a 1920×1080 clip of about 3 seconds; this one is {info['width']}×{info['height']}, {info['duration']:.1f} s")


def render_cover(template: str, title: str, date_text: str, out_path: str, *, title_font: str = "Montserrat",
                 date_font: str = "Prompt Light", profile: Profile = THUS, cancel=None) -> str:
    if not title.strip():
        raise CoverError("title_empty", "Type the episode title first")
    for f in (title_font, date_font):
        if f not in FONT_FILES:
            raise CoverError("font_unknown", f"Unknown font: {f}")
    check_template(template, profile)
    wd = tempfile.mkdtemp(prefix="vidcut_cover_")
    try:
        shutil.copytree(FONTS_DIR, Path(wd, "fonts"))
        Path(wd, "cover.ass").write_text(build_ass(profile, title, date_text, title_font, date_font), encoding="utf-8")
        bx, by, bw, bh = profile.badge_crop
        _run(["-ss", str(profile.badge_at), "-i", template, "-frames:v", "1", "-vf", f"format=rgb24,crop={bw}:{bh}:{bx}:{by}",
              os.path.join(wd, "badge_raw.png")], cancel)
        key = _key_color(os.path.join(wd, "badge_raw.png"), profile)
        cx, cy = profile.scale_center
        a0, fin = profile.date_in
        o0, fout = profile.date_out
        g0, g1 = profile.grow
        s_expr = f"({profile.scale_from}+{1 - profile.scale_from}*clip((t-{g0})/{g1 - g0},0,1))"
        x, y, w, h = profile.clean
        graph = ";".join([
            f"[0:v]delogo=x={x}:y={y}:w={w}:h={h}[bg]",
            f"[1:v]format=rgba,colorkey={key}:0.18:0.1,split=2[b1][b2]",
            f"[b2]fade=t=in:st={a0}:d={fin}:alpha=1,fade=t=out:st={o0}:d={fout}:alpha=1,"
            f"scale=w='{bw}*{s_expr}':h='{bh}*{s_expr}':eval=frame[ba]",
            f"[bg][b1]overlay=x={bx}:y={by}:enable='lt(t,{profile.poster_until})'[v1]",
            f"[v1][ba]overlay=x='{cx}+(w/{bw})*({bx}-{cx})':y='{cy}+(w/{bw})*({by}-{cy})':enable='between(t,{a0},{profile.end})':format=auto[v2]",
            "[v2]ass=cover.ass:fontsdir=fonts:shaping=complex,format=yuv420p[v]"])
        tmp = os.path.join(wd, "out.mp4")
        _run(["-i", template, "-loop", "1", "-framerate", str(FPS), "-t", f"{profile.end}", "-i", os.path.join(wd, "badge_raw.png"),
              "-filter_complex", graph, "-map", "[v]", "-map", "0:a?", "-c:v", "libx264", "-preset", "medium", "-crf", "14",
              "-r", str(FPS), "-c:a", "aac", "-b:a", "192k", "-shortest", tmp], cancel, cwd=wd)
        os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
        shutil.move(tmp, out_path)
        return out_path
    finally:
        shutil.rmtree(wd, ignore_errors=True)


THAI_MONTHS = ["มกราคม", "กุมภาพันธ์", "มีนาคม", "เมษายน", "พฤษภาคม", "มิถุนายน", "กรกฎาคม", "สิงหาคม", "กันยายน", "ตุลาคม",
               "พฤศจิกายน", "ธันวาคม"]


def thai_date(year: int, month: int, day: int) -> str:
    """'วันที่ 22 ตุลาคม  2569' (Buddhist-era year; two spaces before it, as in the sample covers)."""
    return f"วันที่ {day} {THAI_MONTHS[month - 1]}  {year + 543}"


def safe_stem(title: str, limit: int = 80) -> str:
    """A file name stem from a title: no characters Windows forbids, spaces collapsed."""
    s = "".join("_" if ch in '<>:"/\\|?*' or ord(ch) < 32 else ch for ch in title).strip(" .")
    s = " ".join(s.split())
    return (s[:limit].rstrip(" .") or "cover")
