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
