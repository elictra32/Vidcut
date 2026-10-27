import os
import subprocess

from core.export import build_filter_graph, overlay_statements, render_preview_frame, run_export
from core.models import Clip, Keep, Overlay, Project, Selection
from core.presets import PRESETS
from core.timeline import Piece
from tests.helpers import make_clip, has_libass

PNG = None


def make_logo(path, color="red", size="200x100"):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"color=c={color}:s={size}",
                    "-frames:v", "1", path], check=True)
    return path


def test_overlay_statements_position_size_opacity_and_time():
    o = Overlay("o1", "/x/logo.png", x=0.5, y=0.25, width=0.2, opacity=0.5, start=1.0, end=3.0)
    stmts, label = overlay_statements([o], 2, "vc", 1000, 2000)
    assert label == "ovo0"
    assert stmts[0] == "[2:v]scale=200:-1,format=rgba,colorchannelmixer=aa=0.5[ov0]"
    assert "overlay=x=500-w/2:y=500-h/2" in stmts[1]
    assert "enable='between(t,1,3)'" in stmts[1]
    # no time limits -> no enable gate; an untimed preview ignores the gate
    assert "enable" not in overlay_statements([Overlay("o", "p")], 0, "vc", 100, 100)[0][1]
    assert "enable" not in overlay_statements([o], 0, "vc", 100, 100, timed=False)[0][1]


def test_filter_graph_puts_overlay_before_subtitles():
    clip = Clip("c1", "/a.mp4", 4, 640, 360, 25, True, keeps=[Keep(0, 4)])
    g = build_filter_graph([clip], [Piece("c1", 0, 2, 0.0)], PRESETS["tiktok"], "subs.ass",
                           overlays=[Overlay("o1", "/logo.png")])
    assert g.index("overlay=") < g.index("subtitles=")


def _project(tmp_path, logo):
    path = make_clip(str(tmp_path / "a.mp4"), [("tone", 2)], size="640x360")
    clip = Clip("c1", path, 2, 640, 360, 25, True, keeps=[Keep(0, 2)])
    return Project(clips=[clip], selection=Selection(0, 2), overlays=[Overlay("o1", logo, x=0.5, y=0.5, width=0.5)])


def _frame_pixel(png, x, y):
    out = subprocess.run(["ffmpeg", "-loglevel", "error", "-i", png, "-vf", f"crop=1:1:{x}:{y}", "-f", "rawvideo",
                          "-pix_fmt", "rgb24", "-"], capture_output=True, check=True).stdout
    return tuple(out)


def test_preview_frame_shows_the_overlay(tmp_path):
    logo = make_logo(str(tmp_path / "logo.png"))
    proj = _project(tmp_path, logo)
    out = str(tmp_path / "f.png")
    render_preview_frame(proj, 0.5, out)
    r, g, b = _frame_pixel(out, 540, 960)  # centre of a 1080x1920 frame
    assert r > 200 and g < 60 and b < 60
    proj.overlays = []
    render_preview_frame(proj, 0.5, out)
    r, g, b = _frame_pixel(out, 540, 960)
    assert not (r > 200 and g < 60 and b < 60)


def test_export_with_overlay_runs_and_respects_time_gate(tmp_path):
    logo = make_logo(str(tmp_path / "logo.png"))
    proj = _project(tmp_path, logo)
    proj.overlays[0].start, proj.overlays[0].end = 0.0, 0.5
    res = run_export(proj, str(tmp_path / "out"))
    assert os.path.getsize(res.video) > 0
    shots = []
    for t in (0.2, 1.5):
        png = str(tmp_path / f"s{t}.png")
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", str(t), "-i", res.video, "-frames:v", "1", png], check=True)
        shots.append(_frame_pixel(png, 540, 960))
    assert shots[0][0] > 200 and shots[0][1] < 60   # logo visible early
    assert not (shots[1][0] > 200 and shots[1][1] < 60)  # gone later


def test_batched_export_also_gets_the_overlay(tmp_path):
    logo = make_logo(str(tmp_path / "logo.png"))
    path = make_clip(str(tmp_path / "b.mp4"), [("tone", 8)], size="640x360")
    keeps = [Keep(i * 0.5, i * 0.5 + 0.4) for i in range(14)]  # 14 pieces -> more than one batch
    proj = Project(clips=[Clip("c1", path, 8, 640, 360, 25, True, keeps=keeps)],
                   overlays=[Overlay("o1", logo, x=0.5, y=0.5, width=0.5)])
    res = run_export(proj, str(tmp_path / "out"))
    png = str(tmp_path / "s.png")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", "1", "-i", res.video, "-frames:v", "1", png], check=True)
    r, g, b = _frame_pixel(png, 540, 960)
    assert r > 200 and g < 60
