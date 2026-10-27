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
    assert "in_color_matrix=bt709" in f and "colorchannelmixer=rr=0.88:gg=1:bb=1.12" in f and "out_color_matrix=bt709" in f
    assert f.endswith("eq=brightness=0:contrast=1:saturation=1.2")
    assert "bt601" in grade_filter(Grade(temperature=10), "bt601")


def test_the_grade_sits_on_the_source_picture_before_scaling_and_survives_saving():
    clip = Clip("c", "/in.mp4", 10, 1920, 1080, 25, True, keeps=[Keep(0, 10)], grade=Grade(temperature=-30))
    graph = build_filter_graph([clip], [Piece("c", 0, 2, 0)], PRESETS["youtube"], None)
    assert graph.index("colorchannelmixer") < graph.index("scale=1920:1080")
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


def test_a_barely_there_grade_does_not_shift_colours_through_the_rgb_round_trip(tmp_path):
    # warmth works in RGB; converting with ffmpeg's default matrix instead of the picture's own shifted every colour (green/blue
    # off by ~8 levels) and made the exported frame differ a lot from the preview
    src = str(tmp_path / "hd.mp4")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=s=1280x720:d=2:r=25,format=rgb24",
                    "-vf", "scale=out_color_matrix=bt709:out_range=tv,format=yuv420p", "-c:v", "libx264", "-colorspace", "bt709",
                    "-color_primaries", "bt709", "-color_trc", "bt709", src], check=True)
    clip = Clip("c", src, 2, 1280, 720, 25, False, keeps=[Keep(0, 2)])
    proj = Project(clips=[clip], preset="youtube")
    plain, tiny = str(tmp_path / "p.png"), str(tmp_path / "t.png")
    render_preview_frame(proj, 0.5, plain)
    clip.grade = Grade(temperature=0.5)
    render_preview_frame(proj, 0.5, tiny)
    assert all(abs(a - b) <= 3 for a, b in zip(mean_rgb(plain), mean_rgb(tiny)))
