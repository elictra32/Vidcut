import pytest

from core.episodes import plan_episodes, quality_range
from core.models import Clip, Keep
from core.timeline import cut_points

MB = 1048576


def plan(total, **kw):
    kw.setdefault("max_bytes", 500 * MB)
    kw.setdefault("source_kbps", 1700)
    kw.setdefault("preset", "tiktok")
    return plan_episodes([], 0.0, total, **kw)


def test_short_enough_stays_one_episode():
    eps = plan(600)
    assert len(eps) == 1 and (eps[0].start, eps[0].end) == (0.0, 600)


def test_fewest_episodes_that_keep_the_quality_floor():
    # source 1.7 Mbps -> floor 1.19 Mbps video + 0.16 audio: 460 MB holds about 46 minutes of it (45 with the cut-snapping margin)
    one_hour = plan(3600)
    assert len(one_hour) == 2
    assert len(plan(2600)) == 1  # 43 minutes still fits one file at the floor


def test_every_episode_is_within_the_limit_and_above_the_floor():
    floor, cap = quality_range("tiktok", 1700)
    for e in plan(3 * 3600, intros=[("i1", 8.0)], outro_dur=10.0):
        assert e.est_bytes <= 500 * MB
        assert floor * 0.95 <= e.video_kbps <= cap


def test_episodes_tile_the_whole_range_without_gaps():
    eps = plan(7000)
    assert eps[0].start == 0 and eps[-1].end == 7000
    for a, b in zip(eps, eps[1:]):
        assert a.end == b.start


def test_cuts_snap_to_dead_air_boundaries():
    boundaries = [100.0, 1500.0, 1750.0, 1790.0, 2400.0]
    eps = plan_episodes(boundaries, 0, 3600, max_bytes=500 * MB, source_kbps=1700, preset="tiktok")
    assert len(eps) == 2
    assert eps[0].end == 1790.0  # the boundary closest below the ideal midpoint (1800)


def test_each_episode_gets_its_own_intro_and_the_last_one_is_reused():
    eps = plan(3 * 3600, intros=[("a", 5.0), ("b", 6.0)], outro_dur=4.0)
    assert [e.intro_clip_id for e in eps][:3] == ["a", "b", "b"]
    assert len(eps) >= 3


def test_extras_count_against_the_size():
    plain = plan(2600)
    heavy = plan(2600, intros=[("a", 120.0)], outro_dur=120.0)
    assert plain[0].est_bytes < heavy[0].est_bytes or len(heavy) > len(plain)


def test_a_limit_too_small_for_the_floor_is_an_error():
    with pytest.raises(ValueError, match="episode_limit_too_small"):
        plan(3600, max_bytes=5 * MB)


def test_cut_points_are_where_pieces_begin():
    c = Clip("c1", "/a.mp4", 100, 10, 10, 25, True, keeps=[Keep(0, 10), Keep(20, 30), Keep(50, 55, enabled=False), Keep(60, 70)])
    assert cut_points([c]) == [10.0, 20.0]


def test_a_measured_bitrate_lets_episodes_be_longer_and_fewer():
    worst = plan(81 * 60 + 50, source_kbps=1850)              # planned from the worst-case cap: 2 episodes
    assert len(worst) == 2
    measured = plan(81 * 60 + 50, source_kbps=1850, measured_kbps=520)   # the footage really needs about 0.5 Mbps
    assert len(measured) == 1
    e = measured[0]
    assert e.est_bytes < 500 * MB * 0.92                     # expected to fit with room to spare
    assert e.max_bytes <= 500 * MB                           # and the encoder's cap can never exceed the limit
    assert e.est_bytes < e.max_bytes


def test_the_measurement_never_raises_the_cap_and_the_guard_still_bounds_every_episode():
    eps = plan(5 * 3600, source_kbps=1850, measured_kbps=9000)   # a measurement above the cap is capped
    floor, cap = quality_range("tiktok", 1850)
    assert all(e.video_kbps <= cap and e.max_bytes <= 500 * MB for e in eps)
    assert len(eps) >= len(plan(5 * 3600, source_kbps=1850, measured_kbps=520))


def test_sample_windows_spread_evenly_and_shrink_for_short_ranges():
    from core.sizing import sample_windows
    ws = sample_windows(0, 3600)
    assert len(ws) == 4 and ws[0][0] == 0 and ws[-1][1] == 3600 and all(b - a == 8 for a, b in ws)
    assert sample_windows(100, 105) == [(100, 105)]
    assert sample_windows(0, 20) == [(0, 8), (12, 20)]
    assert sample_windows(5, 5) == []


def test_one_clip_limit_gives_a_bitrate_that_fits_or_says_it_cannot():
    import pytest
    from core.episodes import clip_video_kbps
    kbps = clip_video_kbps(50 * 1048576, 60, source_kbps=8000, preset="tiktok")
    assert 300 <= kbps <= 8000 and (kbps + 160) * 1000 / 8 * 60 < 50 * 1048576
    with pytest.raises(ValueError):
        clip_video_kbps(1 * 1048576, 600, source_kbps=8000, preset="tiktok")
