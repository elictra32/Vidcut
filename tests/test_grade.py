import json
import subprocess
from pathlib import Path

import pytest

from core.export import build_filter_graph, render_preview_frame
from core.grade import clamp, grade_filter, grade_params, is_neutral
from core.models import Clip, Grade, Keep, Project, project_from_dict, project_to_dict
from core.presets import PRESETS
from core.timeline import Piece
from tests.helpers import make_clip

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "grade_cases.json").read_text())


def test_params_match_the_shared_fixture_the_preview_is_tested_against():
    for case in FIXTURE:
        got = grade_params(Grade(**case["grade"]))
        assert got == pytest.approx(case["params"], abs=1e-9)


def test_a_neutral_grade_adds_nothing_and_out_of_range_values_are_clamped():
    assert is_neutral(Grade()) and grade_filter(Grade()) == ""
    assert clamp(Grade(temperature=900, contrast=-900)).temperature == 100 and clamp(Grade(contrast=-900)).contrast == -100
    f = grade_filter(Grade(temperature=-40, saturation=20))
    assert f.startswith("colorchannelmixer=rr=0.88:gg=1:bb=1.12,eq=") and "saturation=1.2" in f and "brightness=0:" in f


def test_the_grade_sits_on_the_source_picture_before_scaling_and_survives_saving():
    clip = Clip("c", "/in.mp4", 10, 1920, 1080, 25, True, keeps=[Keep(0, 10)], grade=Grade(temperature=-30))
    graph = build_filter_graph([clip], [Piece("c", 0, 2, 0)], PRESETS["youtube"], None)
    assert graph.index("colorchannelmixer") < graph.index("scale=")
    plain = Clip("c", "/in.mp4", 10, 1920, 1080, 25, True, keeps=[Keep(0, 10)])
    assert "colorchannelmixer" not in build_filter_graph([plain], [Piece("c", 0, 2, 0)], PRESETS["youtube"], None)
    again = project_from_dict(project_to_dict(Project(clips=[clip])))
    assert again.clips[0].grade.temperature == -30


def mean_rgb(png: str) -> tuple[float, float, float]:
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", png, "-vf", "scale=1:1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                         capture_output=True).stdout
    return tuple(float(v) for v in raw[:3])


def test_less_yellow_really_makes_the_exported_frame_bluer(tmp_path):
    src = str(tmp_path / "y.mp4")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=0xC8B450:s=320x180:d=2:r=25", "-pix_fmt", "yuv420p", src], check=True)
    clip = Clip("c", src, 2, 320, 180, 25, False, keeps=[Keep(0, 2)])
    proj = Project(clips=[clip], preset="youtube")
    before, after = str(tmp_path / "a.png"), str(tmp_path / "b.png")
    render_preview_frame(proj, 0.5, before)
    clip.grade = Grade(temperature=-60)
    render_preview_frame(proj, 0.5, after)
    (r0, g0, b0), (r1, g1, b1) = mean_rgb(before), mean_rgb(after)
    assert r1 < r0 - 10 and b1 > b0 + 10 and abs(g1 - g0) < 12
