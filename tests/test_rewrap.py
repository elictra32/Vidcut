from core.models import Subtitle
from core.rewrap import rewrap_subtitles
from core.thai_split import display_width

TEXT = "สวัสดีครับทุกคนวันนี้เรามาตัดต่อวิดีโอกันนะครับ"


def sub(text, a=0.0, b=6.0, **kw):
    return Subtitle("s1", "c1", a, b, text, **kw)


def test_narrower_lines_break_at_word_boundaries_and_respect_the_limit():
    out = rewrap_subtitles([sub(TEXT)], 10, 2)
    assert len(out) >= 2
    for s in out:
        assert all(display_width(row) <= 10 for row in s.text.split("\n")) and len(s.text.split("\n")) <= 2
    assert "".join(s.text.replace("\n", "") for s in out) == TEXT  # no characters lost or reordered


def test_split_pieces_tile_the_original_span_and_keep_position_and_size():
    out = rewrap_subtitles([sub(TEXT, 10.0, 16.0, x=0.3, y=0.8, scale=1.5)], 8, 1)
    assert out[0].src_start == 10.0 and out[-1].src_end == 16.0
    assert all(a.src_end <= b.src_start + 1e-9 for a, b in zip(out, out[1:]))
    assert all((s.x, s.y, s.scale) == (0.3, 0.8, 1.5) for s in out)
    assert len({s.id for s in out}) == len(out) and out[0].id == "s1"


def test_wider_limit_joins_an_existing_manual_break():
    out = rewrap_subtitles([sub("สวัสดีครับ\nทุกคน")], 40, 2)
    assert len(out) == 1 and out[0].text == "สวัสดีครับทุกคน"


def test_latin_words_keep_a_space_when_a_break_is_removed():
    out = rewrap_subtitles([sub("hello\nworld")], 40, 2)
    assert out[0].text == "hello world"


def test_empty_text_is_left_alone():
    assert rewrap_subtitles([sub("  ")], 10, 2)[0].text == "  "
