import json
from pathlib import Path

import pytest

from core.ass import RenderedSub, to_ass
from core.models import SubtitleStyle
from core.reveal import reveal_ends, reveal_schedule

CASES = json.loads((Path(__file__).parent / "fixtures" / "reveal_cases.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", CASES, ids=lambda c: repr(c["text"]))
def test_reveal_ends_match_the_shared_fixture(case):
    assert reveal_ends(case["text"]) == case["ends"]


def test_schedule_tiles_the_line_and_ends_with_the_whole_text():
    text = "สวัสดีครับทุกคน"
    steps = reveal_schedule(text, 10.0, 12.0)
    assert steps[0][0] == 10.0 and steps[-1][1] == 12.0 and steps[-1][2] == len(text)
    for a, b in zip(steps, steps[1:]):
        assert a[1] == pytest.approx(b[0]) and a[2] < b[2]
    assert steps[-1][0] < 12.0 - 0.2 * 2.0 + 0.5  # whole text is up well before the line ends


def test_very_short_lines_do_not_flicker():
    steps = reveal_schedule("a" * 30, 0.0, 0.5)
    assert all(t1 - t0 >= 0.04 for t0, t1, _ in steps[:-1])


def test_to_ass_reveal_keeps_layout_by_hiding_the_rest_instead_of_cutting_it():
    out = to_ass([RenderedSub(1, 3, "ABC", None, None, None, True)], SubtitleStyle(), (1080, 1920))
    lines = [l for l in out.splitlines() if l.startswith("Dialogue")]
    assert len(lines) == 3
    assert lines[0].endswith("A{\\alpha&HFF&}BC") and lines[-1].endswith("ABC")
    assert "0:00:01.00" in lines[0] and "0:00:03.00" in lines[-1].split(",")[2]


def test_to_ass_without_reveal_is_one_event_per_line():
    out = to_ass([RenderedSub(1, 3, "ABC", None, None)], SubtitleStyle(), (1080, 1920))
    assert len([l for l in out.splitlines() if l.startswith("Dialogue")]) == 1
