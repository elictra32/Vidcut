import re
import struct
import subprocess
from pathlib import Path

import numpy as np
import pytest

from core.fonts import FONT_FILES, FONTS_DIR, ass_size_factor
from core.models import SubtitleStyle
from core.ass import RenderedSub, to_ass
from tests.helpers import has_libass

ROOT = Path(__file__).resolve().parent.parent


def win_metrics_factor(path: Path) -> float:
    """(usWinAscent + usWinDescent) / unitsPerEm, read straight from the font tables."""
    d = path.read_bytes()
    n = struct.unpack(">H", d[4:6])[0]
    tables = {}
    for i in range(n):
        tag, _, off, _ln = struct.unpack(">4sIII", d[12 + 16 * i: 28 + 16 * i])
        tables[tag] = off
    upem = struct.unpack(">H", d[tables[b"head"] + 18: tables[b"head"] + 20])[0]
    wa, wd = struct.unpack(">HH", d[tables[b"OS/2"] + 74: tables[b"OS/2"] + 78])
    return (wa + wd) / upem


def has_drawtext() -> bool:
    out = subprocess.run(["ffmpeg", "-hide_banner", "-filters"], capture_output=True, text=True).stdout
    return " drawtext " in out


@pytest.mark.parametrize("family", sorted(FONT_FILES))
def test_ass_size_factor_matches_font_tables(family):
    assert ass_size_factor(family) == pytest.approx(win_metrics_factor(FONTS_DIR / FONT_FILES[family]), abs=1e-6)


def test_unknown_font_has_factor_one():
    assert ass_size_factor("Some System Font") == 1.0


def test_fontsize_in_ass_is_css_size_times_factor():
    out = to_ass([RenderedSub(0, 1, "x", None, None)], SubtitleStyle(font="Sarabun", size=100), (1080, 1920))
    assert f"Style: Default,Sarabun,{round(100 * ass_size_factor('Sarabun'))}," in out


@pytest.mark.skipif(not has_libass(), reason="ffmpeg without libass")
@pytest.mark.parametrize("family", sorted(FONT_FILES))
def test_libass_resolves_each_offered_font_to_itself(tmp_path, family):
    ass = to_ass([RenderedSub(0, 1, "สวัสดี", None, None)], SubtitleStyle(font=family), (640, 360))
    (tmp_path / "t.ass").write_text(ass, encoding="utf-8")
    (tmp_path / "fonts").mkdir()
    for f in FONT_FILES.values():
        (tmp_path / "fonts" / f).write_bytes((FONTS_DIR / f).read_bytes())
    log = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "debug", "-f", "lavfi", "-i", "color=c=black:s=640x360:d=1",
                          "-vf", "ass=t.ass:fontsdir=fonts:shaping=complex", "-frames:v", "1", "-f", "null", "-"],
                         cwd=tmp_path, capture_output=True, text=True).stderr
    m = re.search(r"fontselect: \(([^,]+), \d+, \d+\) -> ([^,]+),", log)
    assert m, log[-500:]
    norm = lambda s: re.sub(r"[\s-]", "", s).lower()
    assert norm(m.group(2)).startswith(norm(family)), f"{family!r} resolved to {m.group(2)!r}"


def ink_width(png: Path) -> int:
    raw = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(png), "-f", "rawvideo",
                          "-pix_fmt", "gray", "-"], capture_output=True).stdout
    img = np.frombuffer(raw, dtype=np.uint8).reshape(-1, 1080)
    cols = np.where((img > 128).any(axis=0))[0]
    return int(cols.max() - cols.min()) if cols.size else 0


@pytest.mark.skipif(not (has_libass() and has_drawtext()), reason="needs libass and drawtext")
@pytest.mark.parametrize("family", ["Sarabun", "Prompt"])
def test_export_text_width_matches_css_em_size(tmp_path, family):
    """drawtext's fontsize is the em size, like CSS. The ASS export of the same size must come out as wide."""
    text = "กขคงจกขคงจ"  # consonants only: no shaping differences between renderers
    em = 100
    font = FONTS_DIR / FONT_FILES[family]
    ref = tmp_path / "ref.png"
    subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=black:s=1080x400:d=1",
                    "-vf", f"drawtext=fontfile={font}:text='{text}':fontsize={em}:fontcolor=white:x=(w-text_w)/2:y=(h-text_h)/2",
                    "-frames:v", "1", str(ref)], check=True)
    style = SubtitleStyle(font=family, size=em, outline_width=0, default_x=0.5, default_y=0.5)
    (tmp_path / "t.ass").write_text(to_ass([RenderedSub(0, 1, text, None, None)], style, (1080, 400)), encoding="utf-8")
    (tmp_path / "fonts").mkdir()
    for f in FONT_FILES.values():
        (tmp_path / "fonts" / f).write_bytes((FONTS_DIR / f).read_bytes())
    out = tmp_path / "ass.png"
    subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=black:s=1080x400:d=1",
                    "-vf", "ass=t.ass:fontsdir=fonts:shaping=complex", "-frames:v", "1", str(out)], cwd=tmp_path, check=True)
    ref_w, ass_w = ink_width(ref), ink_width(out)
    assert ref_w > 300
    assert ass_w == pytest.approx(ref_w, rel=0.05), f"{family}: drawtext {ref_w}px vs ASS {ass_w}px"


def test_every_offered_font_is_declared_in_the_stylesheet():
    css = (ROOT / "web" / "style.css").read_text(encoding="utf-8")
    for family, file in FONT_FILES.items():
        assert f'font-family: "{family}"' in css and f"/fonts/{file}" in css, family


def test_text_advance_matches_what_libass_draws(tmp_path):
    """The width we compute from the font file must agree with the real rendering (ink width, within a few percent)."""
    from core.fonts import text_advance
    text = "Candlestick and Price Pattern II P1"
    ref = tmp_path / "ref.png"
    subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=black:s=1080x200:d=1",
                    "-vf", f"drawtext=fontfile={ROOT / 'fonts' / 'Montserrat-Regular.ttf'}:text='{text}':fontsize=44:fontcolor=white:x=20:y=50",
                    "-frames:v", "1", str(ref)], check=True)
    assert text_advance("Montserrat", text, 44) == pytest.approx(ink_width(ref), rel=0.04)
    assert text_advance("Montserrat", "", 44) == 0
    assert text_advance("Montserrat", "ab", 44, spacing=2) == pytest.approx(text_advance("Montserrat", "ab", 44) + 4)
