import subprocess

from core import media
from tests.helpers import make_clip


def test_probe_basic(tmp_path):
    p = make_clip(str(tmp_path / "a.mp4"), [("tone", 1), ("silence", 1)])
    info = media.probe(p)
    assert abs(info["duration"] - 2.0) < 0.1
    assert info["width"] == 640 and info["height"] == 360
    assert info["has_audio"] is True


def test_probe_no_audio(tmp_path):
    p = make_clip(str(tmp_path / "a.mp4"), [("tone", 1)], with_audio=False)
    assert media.probe(p)["has_audio"] is False


def test_probe_rotation_swaps_dimensions(tmp_path):
    p = make_clip(str(tmp_path / "r.mp4"), [("tone", 1)], rotate=90)
    info = media.probe(p)
    assert info["width"] == 360 and info["height"] == 640


def test_is_browser_playable_h264_aac_mp4_true_hevc_false():
    ok = {"vcodec": "h264", "acodec": "aac", "container": "mov,mp4,m4a,3gp,3g2,mj2"}
    assert media.is_browser_playable(ok) is True
    assert media.is_browser_playable({**ok, "acodec": None}) is True
    assert media.is_browser_playable({**ok, "vcodec": "hevc"}) is False
    assert media.is_browser_playable({**ok, "container": "matroska,webm"}) is False


def test_make_proxy_height_480(tmp_path):
    p = make_clip(str(tmp_path / "a.mp4"), [("tone", 1)], size="1280x720")
    out = str(tmp_path / "proxy.mp4")
    media.make_proxy(p, out)
    h = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                        "stream=height", "-of", "csv=p=0", out], capture_output=True, text=True).stdout
    assert int(h.strip()) == 480


def test_is_browser_playable_webm_vp9_opus():
    webm = {"vcodec": "vp9", "acodec": "opus", "container": "matroska,webm"}
    assert media.is_browser_playable(webm) is True
    assert media.is_browser_playable({**webm, "vcodec": "h264"}) is False  # h264 in mkv/webm: not reliable
    assert media.is_browser_playable({**webm, "container": "matroska"}) is False
