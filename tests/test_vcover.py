from core.vcover import build_ass, fit_title, letter_spacing, wrap


def title_style(ass: str) -> str:
    return next(line for line in ass.splitlines() if line.startswith("Style: Title,"))


def test_thai_titles_get_no_letter_spacing_so_tone_marks_survive():
    # with spacing libass drops the tone mark over an upper vowel (ที่ -> ที), seen on the first vertical covers
    assert letter_spacing("ตื่นได้แล้ว") == 0.0 and letter_spacing("Candlestick II ตอน 2") == 0.0
    assert letter_spacing("Candlestick and Price Pattern") == 1.5
    thai = build_ass("intro", "ตื่นได้แล้ว", "วันที่ 22", "", "Kanit Medium", "Prompt Light", "Prompt Light")
    latin = build_ass("intro", "Price Pattern", "22 Oct", "", "Montserrat", "Prompt Light", "Prompt Light")
    assert title_style(thai).split(",")[13] == "0.0" and title_style(latin).split(",")[13] == "1.5"


def test_long_titles_wrap_inside_the_frame_and_shrink_to_fit_three_lines():
    lines, px = fit_title("Candlestick and Price Pattern II Part One of Two", "Montserrat")
    assert 1 < len(lines) <= 3 and px <= 68
    assert wrap("", "Montserrat", 60, 800) == [""]


def test_every_listed_font_can_make_a_cover(tmp_path):
    from core.fonts import FONT_FILES
    from core.vcover import render_vertical_cover
    assert {"Kanit Medium", "Mitr Medium", "Chakra Petch Medium", "Pridi Medium"} <= set(FONT_FILES)
    out = render_vertical_cover("intro", str(tmp_path / "c.mp4"), title="ตื่นได้แล้ว", date_text="วันที่ 22", title_font="Pridi Medium", date_font="Chakra Petch Medium")
    assert (tmp_path / "c.mp4").stat().st_size > 10000 and out.endswith("c.mp4")


def test_line_breaks_typed_in_a_title_are_kept_and_too_long_lines_still_wrap():
    lines, px = fit_title("Candlestick\nand Price Pattern", "Montserrat")
    assert lines == ["Candlestick", "and Price Pattern"] and px == 68
    four, _ = fit_title("a\nb\nc\nd", "Montserrat")
    assert four == ["a", "b", "c", "d"]
    typed, px_typed = fit_title("THUS Live Onsite (25/10/2026)\nเทรนด์น้ำมัน ทำพอร์ตเปลี่ยนหลัก EP.1", "Montserrat")
    assert len(typed) == 2 and 48 <= px_typed < 68            # both typed lines stay whole, the size gives a little instead
    long_lines, small = fit_title("Candlestick and Price Pattern II Part One of Two Today\nShort", "Montserrat")
    assert long_lines[-1] == "Short" and len(long_lines) <= 3 and small <= 68
