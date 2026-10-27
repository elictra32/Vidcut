import pytest

from core.encode import (AUDIO_KBPS, encoder_args, estimate_bytes, output_extension, video_kbps)
from core.models import ExportSettings, Project, project_from_dict, project_to_dict


def settings(**kw):
    return ExportSettings(**kw)


@pytest.mark.parametrize("preset,quality,kbps", [
    ("tiktok", "high", 8000), ("tiktok", "medium", 5000), ("tiktok", "small", 3000),
    ("youtube", "high", 12000), ("youtube", "medium", 8000), ("youtube", "small", 5000),
])
def test_quality_levels_are_fixed_video_bitrates(preset, quality, kbps):
    assert video_kbps(settings(quality=quality), preset, 60) == kbps


def test_custom_target_size_sets_the_bitrate_for_the_clip_length():
    s = settings(quality="custom", target_mb=10)
    # 10 MiB over 60 s, minus 2% container overhead, minus the audio track
    assert video_kbps(s, "tiktok", 60) == pytest.approx(10 * 1048576 * 0.98 * 8 / 60 / 1000 - AUDIO_KBPS["mp4"], abs=1)


def test_custom_target_never_goes_below_a_watchable_bitrate():
    assert video_kbps(settings(quality="custom", target_mb=0.1), "tiktok", 60) == 300


def test_custom_without_a_target_falls_back_to_medium():
    assert video_kbps(settings(quality="custom", target_mb=None), "tiktok", 60) == 5000


def test_estimate_is_bitrate_times_length_plus_container_overhead():
    est = estimate_bytes(settings(quality="medium"), "tiktok", 60)
    assert est == pytest.approx((5000 + AUDIO_KBPS["mp4"]) * 1000 / 8 * 60 * 1.02, rel=0.001)


def test_estimate_of_a_custom_target_lands_on_the_target():
    est = estimate_bytes(settings(quality="custom", target_mb=10), "youtube", 90)
    assert est == pytest.approx(10 * 1048576, rel=0.01)


def test_estimate_of_nothing_is_zero():
    assert estimate_bytes(settings(), "tiktok", 0) == 0


def test_mp4_args_use_h264_aac_with_a_bounded_bitrate_and_faststart():
    a = encoder_args(settings(quality="medium"), "tiktok", 60)
    assert a[a.index("-c:v") + 1] == "libx264" and a[a.index("-c:a") + 1] == "aac"
    assert a[a.index("-b:v") + 1] == "5000k" and a[a.index("-maxrate") + 1] == "6250k" and a[a.index("-bufsize") + 1] == "10000k"
    assert "+faststart" in a


def test_mov_is_h264_aac_too_and_mkv_has_no_faststart():
    assert encoder_args(settings(container="mov"), "tiktok", 60)[encoder_args(settings(container="mov"), "tiktok", 60).index("-c:v") + 1] == "libx264"
    assert "+faststart" not in encoder_args(settings(container="mkv"), "tiktok", 60)


def test_webm_is_vp9_opus():
    a = encoder_args(settings(container="webm"), "youtube", 60)
    assert a[a.index("-c:v") + 1] == "libvpx-vp9" and a[a.index("-c:a") + 1] == "libopus"
    assert "libx264" not in a and "aac" not in a


@pytest.mark.parametrize("container,ext", [("mp4", "mp4"), ("mov", "mov"), ("mkv", "mkv"), ("webm", "webm")])
def test_output_extension(container, ext):
    assert output_extension(settings(container=container)) == ext


def test_unknown_container_and_quality_fall_back_to_the_defaults():
    s = settings(container="avi", quality="ultra")
    assert output_extension(s) == "mp4" and video_kbps(s, "tiktok", 60) == 5000


def test_export_settings_roundtrip_through_project_json():
    p = Project()
    p.export = ExportSettings(container="mkv", quality="custom", target_mb=25.0, out_dir="D:\\Shorts")
    assert project_from_dict(project_to_dict(p)).export == p.export
    assert Project().export == ExportSettings()  # mp4 / medium / default folder


def test_quality_never_exceeds_a_share_of_the_source_bitrate():
    from core.encode import video_kbps
    s = ExportSettings(quality="high")
    assert video_kbps(s, "tiktok", 60) == 8000                      # unknown source: the table value
    assert video_kbps(s, "tiktok", 60, source_kbps=1800) == 2160   # a 1.8 Mbps phone clip is not inflated to 8 Mbps
    assert video_kbps(s, "tiktok", 60, source_kbps=20000) == 8000  # a rich source is still capped by the table
    assert video_kbps(ExportSettings(quality="small"), "tiktok", 60, source_kbps=1800) == 900
    assert video_kbps(ExportSettings(quality="small"), "tiktok", 60, source_kbps=200) == 800  # never below the floor


def test_custom_target_size_ignores_the_source_bitrate():
    from core.encode import video_kbps
    s = ExportSettings(quality="custom", target_mb=20)
    assert video_kbps(s, "tiktok", 60, source_kbps=100000) == video_kbps(s, "tiktok", 60)


def test_source_video_kbps_from_file_size(tmp_path):
    from core.encode import source_video_kbps
    from core.models import Clip
    f = tmp_path / "a.mp4"
    f.write_bytes(b"0" * 1_000_000)
    c = Clip("c", str(f), 10.0, 100, 100, 25, True)
    assert abs(source_video_kbps([c]) - (1_000_000 * 8 / 10 / 1000 - 128)) < 1
    assert source_video_kbps([]) is None


def test_auto_is_constant_quality_capped_by_the_source():
    s = ExportSettings(quality="auto")
    a = encoder_args(s, "tiktok", 60, source_kbps=1800)
    assert a[a.index("-crf") + 1] == "22"
    assert a[a.index("-maxrate") + 1] == "2160k"  # never more than 120% of the source
    assert "-b:v" not in a
    w = encoder_args(ExportSettings(container="webm", quality="auto"), "tiktok", 60, source_kbps=1800)
    assert "-crf" in w and "-b:v" in w and "libvpx-vp9" in w
    assert ExportSettings().quality == "auto"
