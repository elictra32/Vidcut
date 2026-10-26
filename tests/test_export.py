import json
import os
import subprocess
import threading

import pytest

from core import export
from core.export import ExportError, build_ffmpeg_cmd, build_filter_graph, render_preview_frame, run_export
from core.media import Cancelled
from core.models import Clip, Framing, Keep, Project, Selection, Subtitle
from core.presets import PRESETS
from core.timeline import Piece
from tests.helpers import has_libass, make_clip

needs_libass = pytest.mark.skipif(not has_libass(), reason="ffmpeg without libass")
SPEC = [("tone", 4), ("silence", 2), ("tone", 4)]


def fake_clip(cid="c1", path="/abs/in/clip.mp4", w=1280, h=720, audio=True, framing=None):
    return Clip(id=cid, path=path, duration=10, width=w, height=h, fps=25, has_audio=audio,
                keeps=[Keep(0, 10)], framing=framing or Framing())


def probe_streams(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", path],
                         capture_output=True, text=True).stdout
    return json.loads(out)


def real_project(path, preset="tiktok", sel=(2, 6), audio=True, framing=None):
    info_clip = Clip(id="c1", path=path, duration=10, width=1280, height=720, fps=25, has_audio=audio,
                     keeps=[Keep(0, 4), Keep(6, 10)], framing=framing or Framing())
    return Project(clips=[info_clip], selection=Selection(*sel), preset=preset,
                   subtitles=[Subtitle("s1", "c1", 2.5, 3.5, "สวัสดีครับ")])


def test_filter_graph_concat_and_relative_subtitles():
    pieces = [Piece("c1", 2, 4, 0), Piece("c1", 6, 8, 2)]
    g = build_filter_graph([fake_clip()], pieces, PRESETS["tiktok"], "subs.ass")
    assert "concat=n=2" in g
    assert "subtitles=subs.ass:fontsdir=fonts" in g
    assert "/abs/in" not in g and ":\\" not in g


def test_cmd_uses_input_seek_per_piece_and_script_graph():
    pieces = [Piece("c1", 2, 4, 0), Piece("c1", 6, 8, 2)]
    cmd = build_ffmpeg_cmd([fake_clip()], pieces, PRESETS["tiktok"], "subs.ass", "out.mp4")
    assert cmd.count("-ss") == 2 and cmd.count("-i") == 2
    assert cmd[cmd.index("-ss") + 1] == "2" and cmd[cmd.index("-t") + 1] == "2"
    assert cmd[cmd.index("-filter_complex_script") + 1] == "graph.txt"
    assert cmd[-1] == "out.mp4"
    assert "libx264" in cmd and "aac" in cmd and "+faststart" in cmd


def test_framing_blur_fit_vs_crop():
    pieces = [Piece("c1", 0, 2, 0)]
    blur = build_filter_graph([fake_clip(framing=Framing("blur_fit"))], pieces, PRESETS["tiktok"], "s.ass")
    assert "boxblur" in blur and "overlay" in blur
    crop = build_filter_graph([fake_clip(framing=Framing("crop", 0.25))], pieces, PRESETS["tiktok"], "s.ass")
    assert "crop=1080:1920:'(iw-ow)*0.25'" in crop and "boxblur" not in crop


def test_portrait_source_to_tiktok_is_plain_scale():
    g = build_filter_graph([fake_clip(w=720, h=1280)], [Piece("c1", 0, 2, 0)], PRESETS["tiktok"], "s.ass")
    assert "scale=1080:1920" in g and "boxblur" not in g and "crop=" not in g


def test_clip_without_audio_synthesizes_silence_in_graph():
    g = build_filter_graph([fake_clip(audio=False)], [Piece("c1", 0, 2, 0)], PRESETS["youtube"], "s.ass")
    assert "anullsrc" in g


@needs_libass
def test_export_tiktok_dimensions_and_duration(tmp_path):
    p = make_clip(str(tmp_path / "in.mp4"), SPEC)
    out = tmp_path / "out"
    res = run_export(real_project(p), str(out))
    info = probe_streams(res.mp4)
    v = next(s for s in info["streams"] if s["codec_type"] == "video")
    assert (v["width"], v["height"]) == (1080, 1920)
    assert abs(float(info["format"]["duration"]) - 4.0) < 0.2
    assert os.path.exists(res.srt)
    srt = open(res.srt, encoding="utf-8").read()
    assert "สวัสดีครับ" in srt and "00:00:00,500 --> 00:00:01,500" in srt


@needs_libass
def test_export_path_with_spaces_and_thai_name(tmp_path):
    d = tmp_path / "โฟลเดอร์ ทดสอบ"
    d.mkdir()
    p = make_clip(str(d / "ทดสอบ คลิป.mp4"), SPEC)
    res = run_export(real_project(p, preset="youtube"), str(tmp_path / "out dir"))
    v = next(s for s in probe_streams(res.mp4)["streams"] if s["codec_type"] == "video")
    assert (v["width"], v["height"]) == (1920, 1080)


@needs_libass
def test_export_clip_without_audio_has_audio_stream(tmp_path):
    p = make_clip(str(tmp_path / "n.mp4"), SPEC, with_audio=False)
    res = run_export(real_project(p, audio=False), str(tmp_path / "out"))
    kinds = {s["codec_type"] for s in probe_streams(res.mp4)["streams"]}
    assert kinds == {"video", "audio"}


@pytest.mark.parametrize("sel", [(5, 5), (0, 999)])
def test_export_invalid_selection_raises_ExportError_th(tmp_path, sel):
    p = make_clip(str(tmp_path / "in.mp4"), SPEC)
    with pytest.raises(ExportError) as ei:
        run_export(real_project(p, sel=sel), str(tmp_path / "out"))
    assert ei.value.code == "selection_invalid"
    assert any("฀" <= ch <= "๿" for ch in ei.value.message_th)


def test_export_all_keeps_disabled_raises_ExportError(tmp_path):
    p = make_clip(str(tmp_path / "in.mp4"), SPEC)
    proj = real_project(p)
    for k in proj.clips[0].keeps:
        k.enabled = False
    with pytest.raises(ExportError) as ei:
        run_export(proj, str(tmp_path / "out"))
    assert ei.value.code == "selection_invalid"


@needs_libass
def test_export_cancel_removes_partial(tmp_path):
    p = make_clip(str(tmp_path / "in.mp4"), SPEC)
    ev = threading.Event()
    ev.set()
    out = tmp_path / "out"
    with pytest.raises(Cancelled):
        run_export(real_project(p), str(out), cancel_event=ev)
    assert not out.exists() or list(out.iterdir()) == []


@needs_libass
def test_render_preview_frame_png_dimensions(tmp_path):
    p = make_clip(str(tmp_path / "in.mp4"), SPEC)
    png = str(tmp_path / "f.png")
    render_preview_frame(real_project(p), 1.0, png)
    v = probe_streams(png)["streams"][0]
    assert (v["width"], v["height"]) == (1080, 1920)
