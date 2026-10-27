import json
from pathlib import Path

import pytest

from core import timeline as tl
from core.models import Clip, Keep, Selection, Subtitle

DATA = json.loads((Path(__file__).parent / "fixtures" / "timeline_cases.json").read_text())


def clips_for(name):
    return [Clip(id=c["id"], path="", duration=c["duration"], width=1, height=1, fps=25,
                 has_audio=True, role=c.get("role", "main"), keeps=[Keep(*k) for k in c["keeps"]])
            for c in DATA["projects"][name]]


def call(case):
    clips = clips_for(case["project"])
    fn, a = case["fn"], case["args"]
    if fn == "selection_pieces":
        return [[p.clip_id, p.src_start, p.src_end, p.out_start]
                for p in tl.selection_pieces(clips, Selection(*a))]
    if fn == "subtitle_edited_span":
        r = tl.subtitle_edited_span(clips, Subtitle("s", a[0], a[1], a[2], "x"))
        return list(r) if r else None
    if fn == "edited_to_source":
        return list(tl.edited_to_source(clips, *a))
    return getattr(tl, fn)(clips, *a)


def same(a, b):
    if isinstance(b, list):
        return isinstance(a, (list, tuple)) and len(a) == len(b) and all(same(x, y) for x, y in zip(a, b))
    if isinstance(b, (int, float)) and not isinstance(b, bool):
        return a is not None and abs(a - b) < 1e-6
    return a == b


@pytest.mark.parametrize("case", DATA["cases"], ids=lambda c: f'{c["fn"]}-{c["project"]}-{c["args"]}')
def test_shared_cases(case):
    got = call(case)
    assert same(got, case["expect"]), got


def test_subtitles_for_export_shifts_by_selection_start():
    clips = clips_for("single")
    subs = [Subtitle("a", "c1", 8, 22, "hi"), Subtitle("b", "c1", 41, 45, "cut"),
            Subtitle("c", "c1", 0, 2, "before")]
    out = tl.subtitles_for_export(clips, subs, Selection(5, 15))
    assert [(round(s, 6), round(e, 6), sub.id) for s, e, sub in out] == [(3, 7, "a")]


def test_subtitles_for_export_trims_to_selection():
    clips = clips_for("single")
    out = tl.subtitles_for_export(clips, [Subtitle("a", "c1", 3, 8, "x")], Selection(5, 15))
    assert [(s, e) for s, e, _ in out] == [(0, 3)]


@pytest.mark.parametrize("sel", [(5, 5), (6, 5), (0, 999), (-1, 3)])
def test_selection_invalid_raises(sel):
    with pytest.raises(ValueError, match="selection_invalid"):
        tl.selection_pieces(clips_for("single"), Selection(*sel))


def test_selection_all_keeps_disabled_raises():
    clips = clips_for("single")
    for k in clips[0].keeps:
        k.enabled = False
    with pytest.raises(ValueError, match="selection_invalid"):
        tl.selection_pieces(clips, Selection(0, 1))


def test_selection_time_to_source():
    pieces = tl.selection_pieces(clips_for("multi"), Selection(15, 23))
    assert tl.selection_time_to_source(pieces, 2) == ("c1", 27)
    assert tl.selection_time_to_source(pieces, 6) == ("c2", 1)


def test_a_split_with_nothing_removed_is_one_piece_and_no_cut_point():
    from core.models import Clip, Keep, Selection
    from core.timeline import cut_points, selection_pieces
    c = Clip("c1", "/a.mp4", 100, 10, 10, 25, True, keeps=[Keep(0, 10), Keep(10, 20), Keep(30, 40)])
    pieces = selection_pieces([c], Selection(0, 30))
    assert [(p.src_start, p.src_end) for p in pieces] == [(0, 20), (30, 40)]
    assert cut_points([c]) == [20.0]  # the 10 s split is not a cut; the 20->30 gap is
