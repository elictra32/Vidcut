from pathlib import Path

from core.ass import RenderedSub, to_ass, to_srt
from core.models import SubtitleStyle
from core.presets import PRESETS

GOLDEN = Path(__file__).parent / "golden" / "basic.ass"
SUBS = [RenderedSub(1.5, 3.0, "สวัสดี\nครับ", None, None),
        RenderedSub(3.25, 4.0, "ทดสอบ", 0.25, 0.1)]


def test_to_ass_matches_golden():
    assert to_ass(SUBS, SubtitleStyle(), (1080, 1920)) == GOLDEN.read_text(encoding="utf-8")


def test_to_ass_color_bgr():
    out = to_ass(SUBS, SubtitleStyle(color="#FF0000"), (1080, 1920))
    assert "&H000000FF" in out.split("Style: Default,")[1].split(",")[2]


def test_to_ass_newline_becomes_N():
    assert "สวัสดี\\Nครับ" in to_ass(SUBS, SubtitleStyle(), (1080, 1920))


def test_to_ass_position_from_fractions():
    out = to_ass(SUBS, SubtitleStyle(default_x=0.5, default_y=0.78), (1080, 1920))
    assert "{\\an5\\pos(540,1498)}สวัสดี" in out
    assert "{\\an5\\pos(270,192)}ทดสอบ" in out


def test_to_ass_braces_in_text_are_neutralized():
    out = to_ass([RenderedSub(0, 1, "a{b}c", None, None)], SubtitleStyle(), (1080, 1920))
    assert "a{b}c" not in out


def test_to_ass_background_box_uses_border_style_3():
    style_line = to_ass(SUBS, SubtitleStyle(bg_color="#000000"), (1080, 1920)).split("Style: Default,")[1]
    assert style_line.split(",")[14] == "3"


def test_to_srt_format():
    assert to_srt(SUBS) == ("1\n00:00:01,500 --> 00:00:03,000\nสวัสดี\nครับ\n\n"
                            "2\n00:00:03,250 --> 00:00:04,000\nทดสอบ\n")


def test_presets_pinned_values():
    t, y = PRESETS["tiktok"], PRESETS["youtube"]
    assert (t.width, t.height, t.line_width, t.max_lines) == (1080, 1920, 14, 2)
    assert (y.width, y.height, y.line_width, y.max_lines) == (1920, 1080, 36, 2)
    assert t.style_overrides == {"size": 72, "default_y": 0.70}
    assert y.style_overrides == {"size": 48, "default_y": 0.88}
    assert set(t.safe_zone) == {"top", "bottom", "left", "right"}
