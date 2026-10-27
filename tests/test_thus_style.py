"""The THUS short-style skill: render a synthetic short and measure it back against style.json."""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SKILL = Path(__file__).resolve().parent.parent / ".claude" / "skills" / "thus-short-style"
sys.path.insert(0, str(SKILL / "scripts"))

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None or not (SKILL / "assets" / "endcard.png").exists(),
                                reason="needs ffmpeg and the skill assets")


def _libass():
    out = subprocess.run(["ffmpeg", "-hide_banner", "-filters"], capture_output=True, text=True).stdout
    return " ass " in out


@pytest.fixture(scope="module")
def short(tmp_path_factory):
    if not _libass():
        pytest.skip("ffmpeg without libass")
    d = tmp_path_factory.mktemp("thus")
    for name, col, f in (("cam_top", "0x1c2f6e", 300), ("cam_bottom", "0xc8aa78", 220)):
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"color=c={col}:s=1920x1080:r=25:d=14,drawbox=x='mod(t*200,1500)':y=300:w=200:h=300:color=white@0.6:t=fill",
                        "-f", "lavfi", "-i", f"sine=f={f}:r=48000:d=14", "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", str(d / f"{name}.mp4")], check=True)
    edl = {"cams": {"top": "cam_top.mp4", "bottom": "cam_bottom.mp4"}, "audio": "bottom",
           "title": {"lines": ["จิตใจ", "หลังจากหายไป", "40 ล้าน"]},
           "shots": [{"layout": "split", "t0": 0, "t1": 6.4}, {"layout": "cu", "cam": "bottom", "t0": 6.4, "t1": 9.2},
                     {"layout": "cu", "cam": "top", "t0": 9.2, "t1": 9.32}, {"layout": "cu", "cam": "bottom", "t0": 9.32, "t1": 11.2},
                     {"layout": "split", "t0": 11.2, "t1": 13.0}]}
    (d / "edl.json").write_text(json.dumps(edl), encoding="utf-8")
    r = subprocess.run([sys.executable, str(SKILL / "scripts" / "build_short.py"), str(d / "edl.json"), "-o", str(d / "out.mp4")],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    import measure
    return measure.measure(str(d / "out.mp4")), json.loads((SKILL / "style.json").read_text(encoding="utf-8"))


def test_cuts_land_on_the_edit_list(short):
    m, _ = short
    assert [s["t0"] for s in m["shots"]] == [0.0, 6.4, 9.2, 9.32, 11.2, 13.0]
    assert [s["kind"] for s in m["shots"]] == ["split", "single", "single", "single", "split", "end_card"]
    assert m["end_card"]["start_s"] == 13.0 and m["soft_cuts"] == 0


def test_matches_the_style_targets(short):
    import measure
    m, style = short
    rows, pct = measure.check(m, style)
    assert pct == 100, [r for r in rows if not r["ok"]]


def test_title_is_centred_and_fades_for_a_second(short):
    t = short[0]["title"]
    assert abs(t["ink_width_px"] - 835) <= 15 and abs(t["center"][0] - 534) <= 6 and abs(t["center"][1] - 938) <= 8
    assert 3.9 <= t["full_until_s"] <= 4.3 and 4.8 <= t["gone_s"] <= 5.3


def test_end_card_is_silent_and_loudness_is_on_target(short):
    a = short[0]["audio"]
    assert a["end_card_max_volume_db"] <= -80 and abs(a["lufs"] + 16) <= 1


CUE = """# Cue Sheet

| # | Timestamp | Beat / line | Visual idea | Options |
|---|-----------|-------------|-------------|---------|
| 1 | 00:00–00:03 | HOOK — "ตลาด หุ้น ตก" | chaos | `01_hook_a.gif` 🎞️ · `01_hook_b.mp4` 🎬 · `01_hook_c.png` ✨ |
| 2 | 00:03–00:05 | "ผมแพ้ ทุกวัน" | calm | `02_x.png` 🖼️ |
"""


def test_cue_sheet_to_shots_and_scenes(tmp_path):
    import cue_to_edl
    (tmp_path / "cue-sheet.md").write_text(CUE, encoding="utf-8")
    for n in ("01_hook_a.gif", "01_hook_b.mp4", "01_hook_c.png", "02_x.png"):
        (tmp_path / n).write_bytes(b"x")
    beats = cue_to_edl.parse(CUE)
    assert [(b["t0"], b["t1"]) for b in beats] == [(0, 3), (3, 5)] and beats[0]["text"] == "ตลาด หุ้น ตก"
    assert cue_to_edl.pick(beats[0]["files"], ["video", "gif", "image"], False) == "01_hook_b.mp4"
    assert cue_to_edl.pick(beats[0]["files"], ["gif", "video", "image"], True) == "01_hook_b.mp4"   # --skip-gif never returns the gif
    assert cue_to_edl.pick(beats[1]["files"], ["video", "gif"], False) is None


def test_broll_shot_and_text_scene_media(tmp_path):
    if not _libass():
        pytest.skip("ffmpeg without libass")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=640x360:r=25:d=2", "-pix_fmt", "yuv420p", str(tmp_path / "clip.mp4")], check=True)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=red:s=400x400", "-frames:v", "1", str(tmp_path / "still.png")], check=True)
    for name, col in (("cam_top", "0x1c2f6e"), ("cam_bottom", "0xc8aa78")):
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"color=c={col}:s=1280x720:r=25:d=8", "-f", "lavfi", "-i", "sine=f=220:r=48000:d=8",
                        "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", str(tmp_path / f"{name}.mp4")], check=True)
    edl = {"cams": {"top": "cam_top.mp4", "bottom": "cam_bottom.mp4"}, "audio": "bottom",
           "shots": [{"layout": "split", "t0": 0, "t1": 2}, {"layout": "broll", "file": "clip.mp4", "t0": 2, "t1": 5},
                     {"layout": "broll", "file": "still.png", "t0": 5, "t1": 6.5}]}
    (tmp_path / "edl.json").write_text(json.dumps(edl), encoding="utf-8")
    r = subprocess.run([sys.executable, str(SKILL / "scripts" / "build_short.py"), str(tmp_path / "edl.json"), "-o", str(tmp_path / "b.mp4")], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    import measure
    m = measure.measure(str(tmp_path / "b.mp4"))
    assert abs(m["duration"] - (6.5 + 3.1)) < 0.1 and abs(m["end_card"]["start_s"] - 6.5) < 0.05
    # the still is a solid red frame filling the picture
    f = subprocess.run(["ffmpeg", "-v", "error", "-ss", "5.8", "-i", str(tmp_path / "b.mp4"), "-frames:v", "1", "-vf", "scale=4:4,format=rgb24", "-f", "rawvideo", "-"], capture_output=True).stdout
    assert f[0] > 200 and f[1] < 60

    scenes = {"scenes": [{"lines": ["แพ้", "คือชนะ"], "seconds": 2, "media": "clip.mp4"}, {"lines": ["จบ"], "seconds": 1.5}]}
    (tmp_path / "scenes.json").write_text(json.dumps(scenes, ensure_ascii=False), encoding="utf-8")
    r = subprocess.run([sys.executable, str(SKILL / "scripts" / "text_short.py"), str(tmp_path / "scenes.json"), "-o", str(tmp_path / "t.mp4")], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    d = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(tmp_path / "t.mp4")], capture_output=True, text=True).stdout)
    assert abs(d - 3.5) < 0.1


def test_subtitle_chunking_srt_roundtrip_and_time_mapping(tmp_path):
    pytest.importorskip("pythainlp")
    import subtitles
    import build_short
    cues = subtitles.chunk_segment(10.0, 16.0, "แต่ตอนนี้พวกคุณเก่งก็ยังไม่เก่งความรู้ก็น้อยมากเลยนะครับ")
    assert len(cues) >= 2 and cues[0][0] == 10.0 and abs(cues[-1][1] - 16.0) < 0.05
    assert all(len(line) <= subtitles.MAX_LINE_CHARS + 6 for _, _, t in cues for line in t.split("\n"))
    assert all(len(t.split("\n")) <= 2 for _, _, t in cues)
    assert subtitles.chunk_segment(0, 1, "อ้า...") == []                      # filler-only segments are dropped
    f = tmp_path / "a.srt"
    subtitles.write_srt(cues, f)
    back = subtitles.parse_srt(f.read_text(encoding="utf-8"))
    assert [t for _, _, t in back] == [t for _, _, t in cues] and abs(back[0][0] - 10.0) < 0.002
    # source time -> output time: a shot that starts at source 10 s and sits first in the output
    out = build_short.map_cues([(9.0, 11.0, "x"), (30.0, 31.0, "gone")], [(10.0, 20.0, 0.0)])
    assert out == [(0.0, 1.0, "x")]
    assert "{\\c&H2EB0FF&}10{\\c&HFFFFFF&}" in build_short.subs_ass([(0, 1, "รอ 10 วินาที")])   # numbers are the only accent


def test_add_cover_end_keeps_audio_in_sync_and_cover_is_silent(tmp_path):
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=1080x1920:r=25:d=4", "-f", "lavfi", "-i", "sine=f=440:r=48000:d=4",
                    "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", str(tmp_path / "clip.mp4")], check=True)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=green:s=1080x1920", "-frames:v", "1", str(tmp_path / "cover.png")], check=True)
    r = subprocess.run([sys.executable, str(SKILL / "scripts" / "add_cover_end.py"), str(tmp_path / "clip.mp4"), "--cover", str(tmp_path / "cover.png"),
                        "-o", str(tmp_path / "out.mp4")], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    d = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(tmp_path / "out.mp4")], capture_output=True, text=True).stdout)
    assert abs(d - (3.1 + 4.0 + 3.1)) < 0.1                                   # cover + clip + end card
    def level(ss, t):
        out = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-ss", str(ss), "-t", str(t), "-i", str(tmp_path / "out.mp4"), "-af", "volumedetect", "-f", "null", "-"],
                             capture_output=True, text=True).stderr
        return float(out.split("max_volume:")[1].split("dB")[0])
    assert level(0.2, 2.5) < -80                                              # cover: silence
    assert level(3.5, 3.0) > -30                                              # the clip's own sound starts after the cover
    g = subprocess.run(["ffmpeg", "-v", "error", "-ss", "1", "-i", str(tmp_path / "out.mp4"), "-frames:v", "1", "-vf", "scale=4:4,format=rgb24", "-f", "rawvideo", "-"],
                       capture_output=True).stdout
    assert g[1] > 100 and g[0] < 60                                           # the cover is the green frame


def test_add_cover_end_title_and_custom_end_card(tmp_path):
    if not _libass():
        pytest.skip("ffmpeg without libass")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=0x303030:s=1080x1920:r=25:d=6.5", "-f", "lavfi", "-i", "sine=f=440:r=48000:d=6.5",
                    "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", str(tmp_path / "clip.mp4")], check=True)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=red:s=1080x1920", "-frames:v", "1", str(tmp_path / "card.png")], check=True)
    r = subprocess.run([sys.executable, str(SKILL / "scripts" / "add_cover_end.py"), str(tmp_path / "clip.mp4"), "--title", "VI ปลอม", "--end-card", str(tmp_path / "card.png"),
                        "-o", str(tmp_path / "out.mp4")], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    import measure
    m = measure.measure(str(tmp_path / "out.mp4"))
    assert abs(m["duration"] - 9.6) < 0.1 and m["title"] is not None and 3.9 <= m["title"]["full_until_s"] <= 4.3
    f = subprocess.run(["ffmpeg", "-v", "error", "-ss", "8.5", "-i", str(tmp_path / "out.mp4"), "-frames:v", "1", "-vf", "scale=4:4,format=rgb24", "-f", "rawvideo", "-"], capture_output=True).stdout
    assert f[0] > 200 and f[1] < 60                                           # the custom (red) card is the ending
