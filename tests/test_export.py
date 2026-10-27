import json
import os
import subprocess
import threading

import pytest

from core import export
from core import export as export_mod
from core.export import ExportError, build_ffmpeg_cmd, build_filter_graph, frame_counts, render_preview_frame, run_export
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


def test_cmd_uses_input_seek_per_piece_and_inline_graph():
    pieces = [Piece("c1", 2, 4, 0), Piece("c1", 6, 8, 2)]
    cmd = build_ffmpeg_cmd([fake_clip()], pieces, PRESETS["tiktok"], "subs.ass", "out.mp4")
    assert cmd.count("-ss") == 2 and cmd.count("-i") == 2
    assert cmd[cmd.index("-ss") + 1] == "2" and cmd[cmd.index("-t") + 1] == "2"
    assert "-filter_complex_script" not in cmd  # deprecated in FFmpeg 7+; winget installs current ffmpeg
    assert "concat=n=2" in cmd[cmd.index("-filter_complex") + 1]
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
    info = probe_streams(res.video)
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
    v = next(s for s in probe_streams(res.video)["streams"] if s["codec_type"] == "video")
    assert (v["width"], v["height"]) == (1920, 1080)


@needs_libass
def test_export_clip_without_audio_has_audio_stream(tmp_path):
    p = make_clip(str(tmp_path / "n.mp4"), SPEC, with_audio=False)
    res = run_export(real_project(p, audio=False), str(tmp_path / "out"))
    kinds = {s["codec_type"] for s in probe_streams(res.video)["streams"]}
    assert kinds == {"video", "audio"}


@pytest.mark.parametrize("sel", [(5, 5), (0, 999)])
def test_export_invalid_selection_raises_ExportError_th(tmp_path, sel):
    p = make_clip(str(tmp_path / "in.mp4"), SPEC)
    with pytest.raises(ExportError) as ei:
        run_export(real_project(p, sel=sel), str(tmp_path / "out"))
    assert ei.value.code == "selection_invalid"
    assert ei.value.message_th and ei.value.message_th.isascii()


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


def test_frame_counts_never_accumulate_rounding():
    n = 40
    pieces = [Piece("c1", i * 3.0, i * 3.0 + 1.37, i * 1.37) for i in range(n)]
    frames = frame_counts(pieces)
    assert sum(frames) == round(n * 1.37 * 30)
    assert all(abs(f - 1.37 * 30) <= 1 for f in frames)


def test_filter_graph_makes_every_piece_frame_and_sample_exact():
    pieces = [Piece("c1", 0, 1.37, 0), Piece("c1", 5, 6.37, 1.37)]
    g = build_filter_graph([fake_clip()], pieces, PRESETS["tiktok"], "s.ass")
    frames = frame_counts(pieces)
    for n in frames:
        assert f"trim=end_frame={n}" in g
        assert f"atrim=end_sample={n * 1600}" in g
    assert "tpad=stop=4:stop_mode=clone" in g and "apad=pad_dur=0.15" in g  # bounded: never infinite streams


def media_duration(path, stream):
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", stream, "-show_entries", "stream=duration",
                          "-of", "csv=p=0", path], capture_output=True, text=True).stdout.strip()
    return float(out)


def many_cuts_project(path, n=30, keep=0.7, step=1.3, preset="tiktok", duration=40):
    clip = Clip(id="c1", path=path, duration=duration, width=640, height=360, fps=29.97, has_audio=True,
                keeps=[Keep(i * step, i * step + keep) for i in range(n)])
    return Project(clips=[clip], selection=None, preset=preset)


@needs_libass
def test_export_with_many_cuts_stays_in_sync(tmp_path):
    """Each cut used to leave ~2 frames of extra video, so captions drifted ~2 s over 40 cuts."""
    p = make_clip(str(tmp_path / "in.mp4"), [("tone", 41)], fps="30000/1001")
    proj = many_cuts_project(p, n=20, keep=1.37, step=2.0, duration=41, preset="youtube")
    res = run_export(proj, str(tmp_path / "out"))
    expected = 20 * 1.37
    assert media_duration(res.video, "v:0") == pytest.approx(expected, abs=1 / 30 + 0.01)
    assert media_duration(res.video, "a:0") == pytest.approx(expected, abs=0.06)


@needs_libass
def test_export_with_many_pieces_runs_in_bounded_batches(tmp_path, monkeypatch):
    monkeypatch.setattr(export_mod, "BATCH", 4)
    runs = []
    real = export_mod.media.run_ffmpeg
    monkeypatch.setattr(export_mod.media, "run_ffmpeg", lambda args, *a, **k: (runs.append(list(args)), real(args, *a, **k))[1])
    p = make_clip(str(tmp_path / "in.mp4"), [("tone", 40)])
    res = run_export(many_cuts_project(p, n=10), str(tmp_path / "out"))
    inputs = [a.count("-i") for a in runs]
    assert inputs == [4, 4, 2, 1]  # three batches of <=4 pieces, then one concat + subtitles pass
    assert media_duration(res.video, "v:0") == pytest.approx(10 * 0.7, abs=1 / 30 + 0.01)


@needs_libass
def test_second_export_never_overwrites_the_first(tmp_path):
    p = make_clip(str(tmp_path / "in.mp4"), SPEC)
    out = str(tmp_path / "out")
    first = run_export(real_project(p, sel=(0, 2)), out)
    size1 = os.path.getsize(first.video)
    second = run_export(real_project(p, sel=(1, 4)), out)
    assert second.video != first.video and second.srt != first.srt
    assert os.path.exists(first.video) and os.path.getsize(first.video) == size1
    assert os.path.basename(second.video) == "in_tiktok_2.mp4"


# ---- intro / outro clips -------------------------------------------------------------------------
from core.export import export_pieces  # noqa: E402


def role_clip(cid, role, keeps, path="/abs/x.mp4", duration=100):
    return Clip(id=cid, path=path, duration=duration, width=640, height=360, fps=25, has_audio=True, role=role,
                keeps=[Keep(*k) if isinstance(k, tuple) else k for k in keeps])


def three_part_project(main_path="/abs/main.mp4", intro_path="/abs/intro.mp4", outro_path="/abs/outro.mp4"):
    return Project(clips=[role_clip("intro", "intro", [(0, 2), (3, 4)], intro_path, 10),
                          role_clip("c1", "main", [(0, 10), (20, 30)], main_path, 100),
                          role_clip("outro", "outro", [(0, 1.5), Keep(2, 3, False)], outro_path, 10)])


def test_export_pieces_put_the_intro_before_and_the_outro_after_the_selection():
    pieces, intro_dur = export_pieces(three_part_project(), Selection(5, 15))
    assert intro_dur == 3
    assert [(p.clip_id, p.src_start, p.src_end, p.out_start) for p in pieces] == [
        ("intro", 0, 2, 0), ("intro", 3, 4, 2), ("c1", 5, 10, 3), ("c1", 20, 25, 8), ("outro", 0, 1.5, 13)]


def test_export_pieces_without_extras_are_just_the_selection():
    proj = three_part_project()
    proj.clips = [c for c in proj.clips if c.role == "main"]
    pieces, intro_dur = export_pieces(proj, Selection(0, 4))
    assert intro_dur == 0 and [(p.clip_id, p.out_start) for p in pieces] == [("c1", 0)]


def test_export_pieces_need_a_main_clip():
    proj = three_part_project()
    proj.clips = [c for c in proj.clips if c.role == "intro"]
    with pytest.raises(ValueError, match="selection_invalid"):
        export_pieces(proj, Selection(0, 1))


def test_subtitles_are_shifted_by_the_intro_length():
    proj = three_part_project()
    proj.subtitles = [Subtitle("s1", "c1", 6, 8, "ซับ")]
    _, pieces, rendered = export_mod._prepare(proj, Selection(5, 15))
    assert [(r.start, r.end) for r in rendered] == [(pytest.approx(4.0), pytest.approx(6.0))]  # 6-5 = 1, +3 s of intro


@needs_libass
def test_export_joins_intro_main_and_outro(tmp_path):
    intro = make_clip(str(tmp_path / "intro.mp4"), [("tone", 2)])
    main = make_clip(str(tmp_path / "main.mp4"), SPEC)
    outro = make_clip(str(tmp_path / "outro.mp4"), [("tone", 1.5)])
    proj = Project(clips=[role_clip("intro", "intro", [(0, 2)], intro, 2), role_clip("c1", "main", [(0, 4), (6, 10)], main, 10),
                          role_clip("outro", "outro", [(0, 1.5)], outro, 1.5)],
                   selection=Selection(1, 4), subtitles=[Subtitle("s", "c1", 1.5, 2.5, "ซับกลาง")])
    res = run_export(proj, str(tmp_path / "out"))
    assert media_duration(res.video, "v:0") == pytest.approx(2 + 3 + 1.5, abs=0.1)
    assert "00:00:02,500 --> 00:00:03,500" in open(res.srt, encoding="utf-8").read()


@needs_libass
def test_preview_frame_shows_the_main_timeline_not_the_intro(tmp_path):
    intro = make_clip(str(tmp_path / "intro.mp4"), [("tone", 2)])
    main = make_clip(str(tmp_path / "main.mp4"), SPEC)
    proj = Project(clips=[role_clip("intro", "intro", [(0, 2)], intro, 2), role_clip("c1", "main", [(0, 4)], main, 10)])
    png = str(tmp_path / "f.png")
    render_preview_frame(proj, 1.0, png)
    v = probe_streams(png)["streams"][0]
    assert (v["width"], v["height"]) == (1080, 1920)


# ---- export options: container, target size, output folder --------------------------------------------
from core.models import ExportSettings  # noqa: E402


def format_of(path):
    info = probe_streams(path)
    codecs = {s["codec_type"]: s["codec_name"] for s in info["streams"]}
    return info["format"]["format_name"], codecs


@needs_libass
@pytest.mark.parametrize("container,fmt_part,vcodec,acodec", [
    ("mkv", "matroska", "h264", "aac"), ("mov", "mov", "h264", "aac"), ("webm", "webm", "vp9", "opus")])
def test_export_in_each_container(tmp_path, container, fmt_part, vcodec, acodec):
    p = make_clip(str(tmp_path / "in.mp4"), SPEC)
    proj = real_project(p, preset="youtube", sel=(0, 2))
    proj.export = ExportSettings(container=container)
    res = run_export(proj, str(tmp_path / "out"))
    assert res.video.endswith("." + container) and res.srt.endswith(".srt")
    fmt, codecs = format_of(res.video)
    assert fmt_part in fmt and codecs["video"] == vcodec and codecs["audio"] == acodec


@needs_libass
def test_export_to_a_target_size_stays_near_it(tmp_path):
    p = make_clip(str(tmp_path / "in.mp4"), [("tone", 10)], size="1280x720")
    proj = real_project(p, preset="youtube", sel=(0, 4))
    proj.clips[0].keeps = [Keep(0, 10)]
    proj.export = ExportSettings(quality="custom", target_mb=1.0)
    res = run_export(proj, str(tmp_path / "out"))
    assert os.path.getsize(res.video) <= 1.3 * 1048576


@needs_libass
def test_export_to_a_chosen_folder_with_spaces_and_thai(tmp_path):
    p = make_clip(str(tmp_path / "in.mp4"), SPEC)
    target = tmp_path / "โฟลเดอร์ ส่งออก" / "งาน 1"
    res = run_export(real_project(p, sel=(0, 2)), str(target))
    assert os.path.dirname(res.video) == str(target) and os.path.exists(res.srt)


def test_auto_quality_export_of_easy_footage_is_far_below_the_cap(tmp_path):
    from core.encode import video_kbps
    from core.models import ExportSettings
    path = make_clip(str(tmp_path / "e.mp4"), [("tone", 6)], size="640x360")
    proj = Project(clips=[Clip("c1", path, 6, 640, 360, 25, True, keeps=[Keep(0, 6)])], export=ExportSettings(quality="auto"))
    res = run_export(proj, str(tmp_path / "out"))
    kbps = os.path.getsize(res.video) * 8 / 6 / 1000
    assert kbps < video_kbps(ExportSettings(quality="auto"), "tiktok", 6) * 0.5


@pytest.mark.skipif(not has_libass(), reason="ffmpeg without libass")
def test_reveal_changes_what_the_exported_frame_shows_over_time(tmp_path):
    from core.models import SubtitleStyle
    path = make_clip(str(tmp_path / "r.mp4"), [("tone", 4)], size="640x360")
    sub = Subtitle("s1", "c1", 0.0, 4.0, "ABCDEFGHIJKLMNOPQRSTUVWXYZ")
    style = SubtitleStyle(reveal=True)
    proj = Project(clips=[Clip("c1", path, 4, 640, 360, 25, True, keeps=[Keep(0, 4)])], subtitles=[sub], style=style)
    early, late = str(tmp_path / "e.png"), str(tmp_path / "l.png")
    render_preview_frame(proj, 0.2, early)
    render_preview_frame(proj, 3.8, late)
    plain = Project(clips=proj.clips, subtitles=[sub], style=SubtitleStyle(reveal=False))
    full = str(tmp_path / "f.png")
    render_preview_frame(plain, 3.8, full)
    assert open(early, "rb").read() != open(late, "rb").read()   # the early frame shows less text
    assert open(late, "rb").read() == open(full, "rb").read()     # by the end the line equals the non-reveal rendering
