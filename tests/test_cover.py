import subprocess

import numpy as np
import pytest

from core import media
from core.cover import (CoverError, THUS, build_ass, render_cover, safe_stem, scale_at, thai_date)
from core.fonts import text_advance
from tests.helpers import has_libass

W, H = 1920, 1080


def test_thai_date_uses_the_buddhist_year_and_two_spaces():
    assert thai_date(2026, 10, 22) == "วันที่ 22 ตุลาคม  2569"
    assert thai_date(2026, 9, 23) == "วันที่ 23 กันยายน  2569"
    assert thai_date(2025, 1, 5).startswith("วันที่ 5 มกราคม")


def test_safe_stem():
    assert safe_stem('Part 1: "Intro" / Q&A?') == "Part 1_ _Intro_ _ Q&A_"
    assert safe_stem("   ...  ") == "cover"
    assert len(safe_stem("x" * 300)) == 80


def test_scale_grows_from_the_start_size_to_full_between_the_grow_times():
    a, b = THUS.grow
    assert scale_at(THUS, a - 1) == pytest.approx(THUS.scale_from)
    assert scale_at(THUS, (a + b) / 2) == pytest.approx((1 + THUS.scale_from) / 2)
    assert scale_at(THUS, b + 5) == 1.0


def test_ass_has_the_poster_and_the_animated_events():
    ass = build_ass(THUS, "Trading Record Part 1", "วันที่ 23 กันยายน  2569", "Montserrat", "Sarabun")
    ev = [l for l in ass.splitlines() if l.startswith("Dialogue")]
    assert len(ev) == 6  # poster: box, title, date; animated: box, title, date
    assert any(l.split(",")[3] == "Date" and "\\move" in l for l in ev)
    assert sum("\\fad" in l for l in ev) == 3
    assert ass.count("Trading Record Part 1") == 2


def test_the_box_grows_with_the_title_but_has_a_minimum_width():
    def box_w(title):
        ass = build_ass(THUS, title, "x", "Montserrat", "Sarabun")
        line = next(l for l in ass.splitlines() if "\\p1" in l)
        return float(line.split("{\\p0}")[0].split("l ")[1].split()[0])
    assert box_w("Hi") == THUS.box_min_w
    long_title = "Candlestick and Price Pattern II P1"
    assert box_w(long_title) == pytest.approx(text_advance("Montserrat", long_title, THUS.title_px, THUS.title_spacing) + 2 * THUS.box_pad_x, abs=0.2)


def test_braces_in_a_title_cannot_inject_ass_tags():
    ass = build_ass(THUS, "A{\\fs999}B", "x", "Montserrat", "Sarabun")
    assert "{\\fs999}" not in ass


@pytest.fixture(scope="module")
def template(tmp_path_factory):
    """A stand-in for the THUS template: 1920x1080, 3.1 s, dark purple, with sound."""
    p = str(tmp_path_factory.mktemp("tpl") / "template.mp4")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=0x0e0023:s=1920x1080:r=30:d=3.1",
                    "-f", "lavfi", "-i", "sine=frequency=330:duration=3.1", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
                    "-shortest", p], check=True)
    return p


def frame(path, t):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", str(t), "-i", path, "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                         capture_output=True).stdout
    return np.frombuffer(raw, dtype=np.uint8).reshape(H, W, 3).astype(int)


@pytest.mark.skipif(not has_libass(), reason="ffmpeg without libass")
def test_render_cover_makes_a_3_second_clip_with_the_title_and_date_at_the_right_times(template, tmp_path):
    out = render_cover(template, "Episode Seven", "วันที่ 22 ตุลาคม  2569", str(tmp_path / "cover.mp4"))
    info = media.probe(out)
    assert (info["width"], info["height"]) == (W, H) and info["has_audio"] and info["duration"] == pytest.approx(3.1, abs=0.1)

    def orange_title(img):  # title colour inside the title band
        band = img[715:760, 400:1500]
        return int(((band[:, :, 0] > 200) & (band[:, :, 1] > 90) & (band[:, :, 2] < 110)).sum())

    def white_date(img):
        band = img[800:865, 790:1400]
        return int((band.min(axis=2) > 200).sum())
    assert orange_title(frame(out, 0.2)) > 300 and white_date(frame(out, 0.2)) > 300   # the poster at the start
    assert orange_title(frame(out, 0.8)) == 0 and white_date(frame(out, 0.8)) == 0     # nothing between the poster and the fade-in
    assert orange_title(frame(out, 2.6)) > 300 and white_date(frame(out, 2.6)) > 300   # fully shown
    assert orange_title(frame(out, 3.05)) == 0                                         # gone at the end
    other = render_cover(template, "A Different Title Entirely", "วันที่ 1 มกราคม  2570", str(tmp_path / "cover2.mp4"))
    assert np.abs(frame(out, 2.6) - frame(other, 2.6)).sum() > 100000                   # the text really changed


@pytest.mark.skipif(not has_libass(), reason="ffmpeg without libass")
def test_cover_errors_are_clear(template, tmp_path):
    with pytest.raises(CoverError) as e:
        render_cover(template, "   ", "x", str(tmp_path / "a.mp4"))
    assert e.value.code == "title_empty"
    small = str(tmp_path / "small.mp4")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=black:s=640x360:r=30:d=3", small], check=True)
    with pytest.raises(CoverError) as e:
        render_cover(small, "T", "d", str(tmp_path / "b.mp4"))
    assert e.value.code == "template_mismatch"
    with pytest.raises(CoverError) as e:
        render_cover(template, "T", "d", str(tmp_path / "c.mp4"), title_font="Comic Sans")
    assert e.value.code == "font_unknown"
