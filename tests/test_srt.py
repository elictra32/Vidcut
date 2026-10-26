from pathlib import Path

import pytest

from core.models import Clip, Keep, Selection
from core.presets import PRESETS
from core.srt import Cue, parse_srt
from core.srt_import import clean_cue_text, cues_to_subtitles, effective_windows

SAMPLE = (Path(__file__).parent / "fixtures" / "youtube_sample.srt").read_text(encoding="utf-8")


def clip(duration=300.0, keeps=None):
    return Clip(id="c1", path="x.mp4", duration=duration, width=1280, height=720, fps=25, has_audio=True,
                keeps=keeps or [Keep(0, duration)])


# ---- parser -----------------------------------------------------------------------------------
def test_parse_youtube_sample():
    cues = parse_srt(SAMPLE)
    assert cues[0] == Cue(0.599, 7.960, "มันไบคมันดูดีมากเลยนะ")
    assert cues[3].start == pytest.approx(10.559) and cues[3].text.startswith("นั้นอยู่แล้ว")
    assert all(c.text.strip() for c in cues)  # the blank-text cue at the end is dropped
    assert len(cues) == 28


def test_parse_handles_bom_crlf_and_missing_index():
    raw = "﻿00:00:01,000 --> 00:00:02,500\r\nสวัสดี\r\n\r\n2\r\n00:00:03.250 --> 00:00:04.000\r\nครับ\r\n"
    assert parse_srt(raw) == [Cue(1.0, 2.5, "สวัสดี"), Cue(3.25, 4.0, "ครับ")]


def test_parse_keeps_multiline_text_and_strips_tags():
    cues = parse_srt("1\n00:00:01,000 --> 00:00:03,000\n<i>บรรทัดหนึ่ง</i>\n<font color=\"#fff\">บรรทัดสอง</font> &amp; ก\n")
    assert cues == [Cue(1.0, 3.0, "บรรทัดหนึ่ง\nบรรทัดสอง & ก")]


def test_parse_skips_malformed_and_backwards_blocks():
    raw = "1\nnot a time\nx\n\n2\n00:00:05,000 --> 00:00:04,000\nย้อนหลัง\n\n3\n00:00:06,000 --> 00:00:07,000\nดี\n"
    assert parse_srt(raw) == [Cue(6.0, 7.0, "ดี")]


def test_parse_handles_hours_and_short_millis():
    assert parse_srt("1\n01:02:03,5 --> 01:02:04,25\nx\n") == [Cue(3723.5, 3724.25, "x")]


def test_parse_of_garbage_is_empty():
    assert parse_srt("") == [] and parse_srt("hello world") == []


# ---- cleaning -----------------------------------------------------------------------------------
@pytest.mark.parametrize("raw,expected", [
    ("[เสียงหัวเราะ]", ""), ("เอามา[เสียงหัวเราะ]", "เอามา"), ("[Music] สวัสดี", "สวัสดี"),
    (">> อีกอย่างครับ", "อีกอย่างครับ"), ("- ใช่ครับ", "ใช่ครับ"), ("ก >> ข", "ก ข"),
    ("อือื", ""), ("อื", ""), ("อ่ะ", ""), ("อ้อ", ""), ("ฮึ", ""),
    ("อ", ""), ("เ", ""), ("เออเออ", ""), ("อือ", ""), ("หะ", ""), ("เออ", ""), ("  อึม  ", ""),
    ("เออแต่เดี๋ยวจะไปกินหมูกระทะ", "เออแต่เดี๋ยวจะไปกินหมูกระทะ"),  # a filler inside a sentence is speech: kept
    ("อาจารย์ครับ", "อาจารย์ครับ"), ("ดี", "ดี"),
    ("บรรทัด\nสอง", "บรรทัดสอง"), ("level\nrate", "level rate"),
])
def test_clean_cue_text(raw, expected):
    assert clean_cue_text(raw) == expected


# ---- YouTube's rolling captions: a cue's end is when the line disappears, not when speech ended -----
def test_effective_windows_use_the_next_cue_start_as_the_end():
    cues = [Cue(0.599, 7.96, "มันไบคมันดูดีมากเลยนะ"), Cue(4.96, 10.559, "x" * 40), Cue(7.96, 15.48, "y" * 40)]
    w = effective_windows(cues)
    assert (w[0].start, w[0].end) == pytest.approx((0.599, 4.96))
    assert (w[1].start, w[1].end) == pytest.approx((4.96, 7.96))


def test_effective_windows_cap_a_long_tail_by_speaking_rate():
    w = effective_windows([Cue(10.0, 13.0, "ขึ้น")])  # 4 characters shown for 3 s: speech was ~1 s
    assert w[0].end - w[0].start == pytest.approx(1.0)


def test_effective_windows_stay_monotonic_even_with_equal_starts():
    w = effective_windows([Cue(5.0, 9.0, "a" * 30), Cue(5.0, 9.0, "b" * 30)])
    assert w[0].end <= w[1].start + 1e-9 and w[1].end > w[1].start


def test_a_dropped_filler_cue_still_ends_the_sentence_before_it():
    """'เออเออ' is not shown, but it is when the previous sentence stopped being spoken."""
    cues = [Cue(10.559, 18.679, "นั้นอยู่แล้วไม่ไกลบ้านไงตรงนั้นน่ะ"), Cue(15.48, 18.679, "เออเออ")]
    w = effective_windows(cues)
    assert len(w) == 1 and (w[0].start, w[0].end) == pytest.approx((10.559, 15.48))


def test_effective_windows_drop_a_cue_that_repeats_the_previous_text():
    w = effective_windows([Cue(1.0, 3.0, "สวัสดีครับ"), Cue(2.0, 4.0, "สวัสดีครับ")])
    assert len(w) == 1


# ---- conversion to source-anchored subtitles ---------------------------------------------------
def convert(**kw):
    args = dict(clips=[clip()], clip_id="c1", cues=parse_srt(SAMPLE), preset=PRESETS["tiktok"])
    args.update(kw)
    return cues_to_subtitles(**args)


def strip(s):
    return s.replace("\n", "").replace(" ", "")


def test_conversion_loses_and_duplicates_no_characters():
    subs = convert()
    got = strip("".join(s.text for s in subs))
    expected = strip("".join(clean_cue_text(c.text) for c in parse_srt(SAMPLE)))
    assert got == expected and got  # words split across cues ("แถว" | "นั้น") come out whole, nothing is lost


def test_conversion_drops_fillers_and_tags():
    text = "\n".join(s.text for s in convert())
    assert "[" not in text and ">>" not in text
    assert not any(strip(s.text) in ("เออเออ", "อ", "เ", "หะ", "เออ") for s in convert())


def test_conversion_times_are_ordered_inside_the_cue_range_and_anchored_to_the_clip():
    subs = convert()
    assert all(s.clip_id == "c1" and s.src_end > s.src_start for s in subs)
    assert all(a.src_start <= b.src_start for a, b in zip(subs, subs[1:]))
    assert subs[0].src_start == pytest.approx(0.599, abs=0.01)
    assert max(s.src_end for s in subs) <= 3 * 60 + 18.3


def test_conversion_lines_respect_the_preset_width():
    from core.thai_split import display_width
    for s in convert():
        rows = s.text.split("\n")
        assert len(rows) <= PRESETS["tiktok"].max_lines
        assert all(display_width(r) <= PRESETS["tiktok"].line_width + 12 for r in rows)  # an oversize word keeps its own row


def test_conversion_applies_the_time_offset():
    base, shifted = convert(), convert(offset=2.5)
    assert [s.text for s in base] == [s.text for s in shifted]
    assert all(b.src_start + 2.5 == pytest.approx(s.src_start) for b, s in zip(base, shifted))


def test_conversion_clamps_to_the_clip_and_drops_what_falls_outside():
    subs = convert(clips=[clip(duration=20.0)])
    assert subs and all(0 <= s.src_start < s.src_end <= 20.0 for s in subs)
    assert convert(offset=-1000.0) == []


def test_conversion_only_selection_keeps_cues_in_the_selected_source_ranges():
    clips = [clip(keeps=[Keep(0, 40), Keep(50, 120)])]
    # edited 0..30 -> source 0..30 only
    subs = convert(clips=clips, selection=Selection(0, 30))
    assert subs and max(s.src_start for s in subs) < 30
    assert not any("เมื่อกี้" in s.text for s in subs)  # that cue is at 1:47
    everything = convert(clips=clips)
    assert len(everything) > len(subs)


def test_conversion_selection_across_a_cut_skips_the_removed_cues():
    clips = [clip(keeps=[Keep(0, 20), Keep(100, 200)])]
    subs = convert(clips=clips, selection=Selection(0, 90))  # source 0..20 and 100..170
    starts = [s.src_start for s in subs]
    assert any(s < 20 for s in starts) and any(100 <= s < 170 for s in starts)
    assert not any(20 <= s < 99 for s in starts)


def test_conversion_of_empty_cue_list_is_empty():
    assert convert(cues=[]) == []
