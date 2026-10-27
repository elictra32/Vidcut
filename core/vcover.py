"""Vertical (1080x1920, TikTok / Reels / Shorts) front and back covers, drawn from scratch in the THUS look: aubergine
gradient, the white logo, the episode title in white with an orange accent line and the date in an orange pill beneath it, all kept clear of the
app overlays (top 10 %, bottom 20 %, right 15 % of the frame). The landscape sample covers can't be reused: there is no
vertical original to copy, so this is a new design in the same colours and fonts."""
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import numpy as np

from core.cover import CoverError, _ass_color, _escape, _run, _ts
from core.fonts import FONT_FILES, FONTS_DIR, ass_size_factor, text_advance
from core.media import FFmpegError, find_ffmpeg, no_window, probe
from core.names import safe_stem  # noqa: F401

VW, VH = 1080, 1920
FPS = 30
LOGO_DIR = Path(__file__).resolve().parent.parent / "assets" / "logos"
BG_TOP, BG_BOTTOM = "3B1D52", "14081C"   # lighter aubergine fading to near black
ORANGE, WHITE = "F5853E", "FFFFFF"
DARK, SOFT = "281237", "DDD6E6"     # aubergine for text on orange; a soft lavender white for secondary lines
ASS_ORANGE = "3E85F5"                 # ORANGE as the BGR order ASS drawing colours use
BOX_W = 840                               # widest a title line may be: inside the right-hand safe margin
DURATION = {"intro": 3.1, "outro": 3.0}
DEFAULT_OUTRO_TEXT = "ขอบคุณที่รับชม\nติดตาม THUS ไว้\nไม่พลาดตอนต่อไป"


def pill(w: float, h: float) -> str:
    """An ASS drawing of a rounded bar (fully round ends), centred on its own box."""
    r, k = h / 2, 0.5523 * h / 2
    return (f"m {r:.1f} 0 l {w - r:.1f} 0 b {w - r + k:.1f} 0 {w:.1f} {r - k:.1f} {w:.1f} {r:.1f} b {w:.1f} {r + k:.1f} {w - r + k:.1f} {h:.1f} {w - r:.1f} {h:.1f} "
            f"l {r:.1f} {h:.1f} b {r - k:.1f} {h:.1f} 0 {r + k:.1f} 0 {r:.1f} b 0 {r - k:.1f} {r - k:.1f} 0 {r:.1f} 0")


def wrap(text: str, font: str, px: float, max_w: float, spacing: float = 0.0) -> list[str]:
    """Greedy line breaks by measured width. Thai has no spaces, so it is cut at dictionary words."""
    try:
        from pythainlp.tokenize import word_tokenize
        words = [w for w in word_tokenize(text, engine="newmm", keep_whitespace=True) if w]
    except Exception:  # noqa: BLE001  (no Thai tokenizer: break at spaces only)
        words = [w + " " for w in text.split(" ")]
    lines, cur = [], ""
    for w in words:
        trial = cur + w
        if cur and text_advance(font, trial.strip(), px, spacing) > max_w:
            lines.append(cur.strip())
            cur = w.lstrip()
        else:
            cur = trial
    if cur.strip():
        lines.append(cur.strip())
    return lines or [""]


def letter_spacing(text: str) -> float:
    """A little air between Latin letters. Thai gets none: libass places spaced glyphs one by one and then drops the
    tone marks that stack above a vowel (ที่ becomes ที)."""
    return 0.0 if re.search("[\u0e00-\u0e7f]", text) else 1.5


def fit_title(title: str, font: str, spacing: float = 1.5) -> tuple[list[str], float]:
    """The largest size (from 68 px down) at which the title fits in at most 3 lines of the box."""
    for px in (68, 60, 54, 48, 42):
        lines = wrap(title, font, px, BOX_W, spacing)
        if len(lines) <= 3:
            return lines, px
    return wrap(title, font, 42, BOX_W, spacing)[:3], 42


def build_ass(kind: str, title: str, date_text: str, outro_text: str, title_font: str, date_font: str, outro_font: str) -> str:
    tf, df, of = ass_size_factor(title_font), ass_size_factor(date_font), ass_size_factor(outro_font)
    end = DURATION[kind]
    out = [
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {VW}", f"PlayResY: {VH}", "WrapStyle: 2", "ScaledBorderAndShadow: yes", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, "
        "StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: Box,{title_font},20,&H00000000,&H000000,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,0,0,5,0,0,0,1"]
    events = ["", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"]

    def style(name, font, px, color, spacing=0.0, factor=1.0):
        out.append(f"Style: {name},{font},{round(px * factor)},{_ass_color(color)},&H000000,&H00000000,&H00000000,0,0,0,0,100,100,{spacing},0,1,0,0,5,0,0,0,1")

    def ev(style_name, a, b, tags, text):
        events.append(f"Dialogue: 0,{_ts(a)},{_ts(b)},{style_name},,0,0,0,,{{{tags}}}{text}")

    fade_out = 0.3
    fo = round(fade_out * 1000)
    cx = VW / 2

    def bar(y, a, w=140, h=6):
        ev("Box", a, end, f"\\an5\\pos({cx},{y})\\1c&H{ASS_ORANGE}&\\bord0\\shad0\\p1\\fscx0\\t(0,700,\\fscx100)\\fad(200,{fo})",
           f"m 0 0 l {w} 0 {w} {h} 0 {h}" + "{\\p0}")

    if kind == "intro":
        spacing = letter_spacing(title)
        lines, px = fit_title(title.strip(), title_font, spacing)
        line_h = px * 1.4
        style("Title", title_font, px, WHITE, spacing, tf)
        style("Date", date_font, 46, DARK, 0.0, df)
        bar(715, 0.8)
        top = 790
        grow = f"\\fscx94\\fscy94\\t(0,1500,\\fscx100\\fscy100)\\fad(500,{fo})"
        for i, ln in enumerate(lines):
            ev("Title", 0.9, end, f"\\pos({cx},{top + line_h * (i + 0.5):.0f}){grow}", _escape(ln))
        pill_y = top + line_h * len(lines) + 95
        w = text_advance(date_font, date_text.strip(), 46) + 100
        ev("Box", 1.25, end, f"\\an5\\pos({cx},{pill_y:.0f})\\1c&H{ASS_ORANGE}&\\bord0\\shad0\\p1\\fad(400,{fo})", pill(w, 84) + "{\\p0}")
        ev("Date", 1.25, end, f"\\pos({cx},{pill_y + 3:.0f})\\fad(400,{fo})", _escape(date_text.strip()))
    else:
        style("Out1", outro_font, 66, WHITE, 0.0, of)
        style("Out", outro_font, 52, SOFT, 0.0, of)
        rows = [ln.strip() for ln in outro_text.splitlines() if ln.strip()][:4]
        bar(1005, 0.6)
        for i, ln in enumerate(rows):
            y = 1090 + (0 if i == 0 else 20) + 82 * i
            ev("Out1" if i == 0 else "Out", 0.8 + 0.15 * i, end, f"\\pos({cx},{y})\\fad(400,{fo})", _escape(ln))
    return "\n".join(out + events) + "\n"


def _background(path: str, glow_y: float) -> None:
    """The aubergine backdrop as a PNG: a vertical fade with a soft lavender glow behind the logo."""
    y = np.linspace(0, 1, VH, dtype=np.float32)[:, None, None]
    top = np.array([int(BG_TOP[i:i + 2], 16) for i in (0, 2, 4)], np.float32)
    bottom = np.array([int(BG_BOTTOM[i:i + 2], 16) for i in (0, 2, 4)], np.float32)
    img = top * (1 - y) + bottom * y
    yy, xx = np.mgrid[0:VH, 0:VW].astype(np.float32)
    glow = np.exp(-(((xx - VW / 2) / 520) ** 2 + ((yy - glow_y) / 620) ** 2))[:, :, None]
    img = img + glow * (np.array([0x72, 0x67, 0x7B], np.float32) - img) * 0.28
    img = img + np.random.default_rng(1).uniform(-1.2, 1.2, img.shape).astype(np.float32)   # dither: hides banding in the fade
    raw = np.clip(img, 0, 255).astype(np.uint8)
    ffmpeg, _ = find_ffmpeg()
    subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{VW}x{VH}", "-i", "-",
                    "-frames:v", "1", path], input=raw.tobytes(), check=True, **no_window())


def render_vertical_cover(kind: str, out_path: str, *, title: str = "", date_text: str = "", outro_text: str = DEFAULT_OUTRO_TEXT,
                          title_font: str = "Montserrat", date_font: str = "Prompt Light", outro_font: str = "Prompt Light", logo: str = "THUS_logo_white.png",
                          cancel=None, still_at: float | None = None, sound: str | None = None) -> str:
    """Make the cover clip at `out_path`; with `still_at` (seconds) only one PNG of that moment is made, as a quick preview."""
    if kind not in DURATION:
        raise CoverError("cover_kind", "Unknown cover kind")
    if kind == "intro" and not title.strip():
        raise CoverError("title_empty", "Type the episode title first")
    for f in (title_font, date_font, outro_font):
        if f not in FONT_FILES:
            raise CoverError("font_unknown", f"Unknown font: {f}")
    logo_path = LOGO_DIR / logo
    if not logo_path.is_file():
        raise CoverError("logo_missing", "The logo file is missing", str(logo_path))
    end = DURATION[kind]
    if sound:
        try:
            if not probe(sound)["has_audio"]:
                raise CoverError("sound_no_audio", "That clip has no sound to use", sound)
        except FFmpegError as e:
            raise CoverError("unreadable_media", "The sound file is damaged or unreadable", e.details) from e
    wd = tempfile.mkdtemp(prefix="vidcut_vcover_")
    try:
        shutil.copytree(FONTS_DIR, Path(wd, "fonts"))
        Path(wd, "cover.ass").write_text(build_ass(kind, title, date_text, outro_text, title_font, date_font, outro_font), encoding="utf-8")
        shutil.copy(logo_path, Path(wd, "logo.png"))
        logo_y = 560 if kind == "intro" else 700            # centre of the logo
        s = "(0.88+0.12*clip(t/1.6,0,1))"
        _background(os.path.join(wd, "bg.png"), logo_y)
        graph = ";".join([
            "[2:v]format=yuv420p[bg]",
            f"[0:v]format=rgba,scale=w='560*{s}':h=-1:eval=frame,fade=t=in:st=0.15:d=0.6:alpha=1,fade=t=out:st={end - 0.3}:d=0.3:alpha=1[lg]",
            f"[bg][lg]overlay=x='(W-w)/2':y='{logo_y}-h/2':format=auto[v1]",
            "[v1]ass=cover.ass:fontsdir=fonts:shaping=complex,format=yuv420p[v]"])
        tmp = os.path.join(wd, "out.png" if still_at is not None else "out.mp4")
        silent = ["-f", "lavfi", "-t", f"{end}", "-i", "anullsrc=r=44100:cl=stereo"]
        if sound:  # the sound of another clip (e.g. the landscape cover): from its start, cut or padded to the cover, faded out
            audio_in = ["-i", sound]
            graph += (f";[1:a]aresample=44100,aformat=channel_layouts=stereo,atrim=0:{end},asetpts=PTS-STARTPTS,"
                      f"afade=t=out:st={end - 0.4}:d=0.4,apad=whole_dur={end}[ac]")
            amap = "[ac]"
        else:
            audio_in, amap = silent, "1:a"
        inputs = ["-loop", "1", "-framerate", str(FPS), "-t", f"{end}", "-i", os.path.join(wd, "logo.png")] + audio_in + [
                  "-loop", "1", "-framerate", str(FPS), "-t", f"{end}", "-i", os.path.join(wd, "bg.png"), "-filter_complex", graph]
        if still_at is not None:
            _run(inputs + ["-map", "[v]", "-ss", f"{min(max(still_at, 0.0), end - 0.1)}", "-frames:v", "1", tmp], cancel, cwd=wd)
        else:
            _run(inputs + ["-map", "[v]", "-map", amap, "-c:v", "libx264", "-preset", "medium", "-crf", "16", "-r", str(FPS),
                           "-c:a", "aac", "-b:a", "128k", "-t", f"{end}", "-movflags", "+faststart", tmp], cancel, cwd=wd)
        os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
        shutil.move(tmp, out_path)
        return out_path
    finally:
        shutil.rmtree(wd, ignore_errors=True)
