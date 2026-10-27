import json
import os
import threading
import time

import pytest
from fastapi.testclient import TestClient

from core import media
from core.models import Clip, Keep, Project
from server import app as app_module
from server.app import create_app
from server.jobs import JobRunner
from server.project_store import load_project, save_project
from tests.helpers import has_libass, make_clip

SPEC = [("tone", 1), ("silence", 2), ("tone", 1)]


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.delenv("VIDCUT_PICK_OVERRIDE", raising=False)
    monkeypatch.delenv("VIDCUT_FAKE_WHISPER", raising=False)
    return TestClient(create_app(home=str(tmp_path / "home")), base_url="http://127.0.0.1:8765")


def wait_job(client, job_id, timeout=90):
    end = time.time() + timeout
    while time.time() < end:
        j = client.get(f"/api/jobs/{job_id}").json()
        if j["state"] in ("done", "error", "cancelled"):
            return j
        time.sleep(0.1)
    raise AssertionError("job did not finish")


def add_clip(client, path):
    r = client.post("/api/clips", json={"path": path})
    assert r.status_code == 200, r.text
    return r.json()


def get_project(client):
    return client.get("/api/project").json()["project"]


def put_project(client, **changes):
    p = get_project(client)
    p.update(changes)
    assert client.put("/api/project", json=p).status_code == 200


def test_project_roundtrip_atomic(tmp_path, monkeypatch):
    proj = Project(clips=[Clip("c1", "/x.mp4", 5, 640, 360, 25, True, keeps=[Keep(0, 5)])])
    save_project(proj, str(tmp_path))
    assert load_project(str(tmp_path)) == proj
    assert [f for f in os.listdir(tmp_path) if f.endswith(".tmp")] == []
    monkeypatch.setattr(os, "replace", lambda *a: (_ for _ in ()).throw(OSError("boom")))
    with pytest.raises(OSError):
        save_project(Project(), str(tmp_path))
    monkeypatch.undo()
    assert load_project(str(tmp_path)) == proj  # old file intact


def test_load_project_missing_returns_empty(tmp_path):
    assert load_project(str(tmp_path / "nope")) == Project()


def test_add_clip_probes_and_skips_proxy_for_h264_mp4(client, tmp_path):
    p = make_clip(str(tmp_path / "a.mp4"), SPEC)
    out = add_clip(client, p)
    clip = out["clip"]
    assert out["job"] is None and clip["proxy_path"] is None
    assert clip["duration"] == pytest.approx(4, abs=0.1)
    assert clip["keeps"] == [{"start": 0, "end": pytest.approx(4, abs=0.1), "enabled": True}]
    assert get_project(client)["clips"][0]["id"] == clip["id"]


def test_add_clip_makes_proxy_for_non_playable_container(client, tmp_path):
    p = make_clip(str(tmp_path / "a.mkv"), SPEC)
    out = add_clip(client, p)
    assert out["job"]
    assert wait_job(client, out["job"])["state"] == "done"
    proxy = get_project(client)["clips"][0]["proxy_path"]
    assert proxy and os.path.exists(proxy)


def test_corrupt_file_returns_thai_error(client, tmp_path):
    bad = tmp_path / "bad.mp4"
    bad.write_bytes(b"not a video at all")
    r = client.post("/api/clips", json={"path": str(bad)})
    assert r.status_code == 400
    err = r.json()["error"]
    assert err["code"] == "unreadable_media"
    assert err["message"] and err["message"].isascii()


def test_missing_file_returns_thai_error(client, tmp_path):
    r = client.post("/api/clips", json={"path": str(tmp_path / "gone.mp4")})
    assert r.status_code == 404 and r.json()["error"]["code"] == "file_missing"


def test_pick_endpoint_uses_override_env(client, tmp_path, monkeypatch):
    p = make_clip(str(tmp_path / "a.mp4"), SPEC)
    monkeypatch.setenv("VIDCUT_PICK_OVERRIDE", p)
    assert client.post("/api/clips/pick").json()["clip"]["path"] == p


def test_media_endpoint_supports_range(client, tmp_path):
    cid = add_clip(client, make_clip(str(tmp_path / "a.mp4"), SPEC))["clip"]["id"]
    r = client.get(f"/media/{cid}", headers={"Range": "bytes=0-99"})
    assert r.status_code == 206 and len(r.content) == 100
    assert client.get("/media/unknown").status_code == 404


def test_put_project_invalid_returns_422_thai(client):
    r = client.put("/api/project", json={"clips": [{"nope": 1}]})
    assert r.status_code == 422 and r.json()["error"]["code"] == "project_invalid"


def test_silence_job_updates_keeps(client, tmp_path):
    cid = add_clip(client, make_clip(str(tmp_path / "a.mp4"), SPEC))["clip"]["id"]
    r = client.post(f"/api/clips/{cid}/silence", json={"noise_db": -35, "min_silence": 0.6, "padding": 0.15})
    j = wait_job(client, r.json()["job"])
    assert j["state"] == "done", j
    keeps = get_project(client)["clips"][0]["keeps"]
    assert len(keeps) == 2 and keeps[0]["end"] == pytest.approx(1.15, abs=0.08)


def test_job_events_sse_stream_ends_with_done(client, tmp_path):
    cid = add_clip(client, make_clip(str(tmp_path / "a.mp4"), SPEC))["clip"]["id"]
    job = client.post(f"/api/clips/{cid}/silence", json={}).json()["job"]
    with client.stream("GET", f"/api/jobs/{job}/events") as r:
        events = [json.loads(line[6:]) for line in r.iter_lines() if line.startswith("data: ")]
    assert events and events[-1]["state"] == "done"


def test_waveform_endpoint(client, tmp_path):
    cid = add_clip(client, make_clip(str(tmp_path / "a.mp4"), SPEC))["clip"]["id"]
    peaks = client.get(f"/api/clips/{cid}/waveform?points=50").json()["peaks"]
    assert len(peaks) == 50


def test_transcribe_with_fake_whisper_creates_subtitles(client, tmp_path, monkeypatch):
    monkeypatch.setenv("VIDCUT_FAKE_WHISPER", "1")
    cid = add_clip(client, make_clip(str(tmp_path / "a.mp4"), [("tone", 8)]))["clip"]["id"]
    put_project(client, selection={"start": 0, "end": 8})
    j = wait_job(client, client.post("/api/transcribe", json={"model": "small"}).json()["job"])
    assert j["state"] == "done", j
    subs = get_project(client)["subtitles"]
    assert subs and all(s["clip_id"] == cid and s["text"] for s in subs)


def test_transcribe_without_selection_is_clear_error(client, tmp_path):
    add_clip(client, make_clip(str(tmp_path / "a.mp4"), SPEC))
    r = client.post("/api/transcribe", json={})
    assert r.status_code == 400 and r.json()["error"]["code"] == "no_selection"


def test_transcribe_no_audio_returns_thai_error(client, tmp_path, monkeypatch):
    monkeypatch.setenv("VIDCUT_FAKE_WHISPER", "1")
    add_clip(client, make_clip(str(tmp_path / "n.mp4"), [("tone", 4)], with_audio=False))
    put_project(client, selection={"start": 0, "end": 4})
    j = wait_job(client, client.post("/api/transcribe", json={}).json()["job"])
    assert j["state"] == "error" and j["error"]["code"] == "no_audio"
    assert j["error"]["message"] and j["error"]["message"].isascii()


@pytest.mark.skipif(not has_libass(), reason="ffmpeg without libass")
def test_export_job_produces_mp4_and_srt(client, tmp_path):
    add_clip(client, make_clip(str(tmp_path / "a.mp4"), [("tone", 4)]))
    put_project(client, selection={"start": 0, "end": 2})
    j = wait_job(client, client.post("/api/export", json={"preset": "youtube"}).json()["job"])
    assert j["state"] == "done", j
    mp4, srt = j["result"]["video"], j["result"]["srt"]
    assert client.get(f"/exports/{mp4}").status_code == 200
    assert client.get(f"/exports/{srt}").status_code == 200
    assert get_project(client)["preset"] == "youtube"


def test_export_invalid_selection_job_error_is_thai(client, tmp_path):
    add_clip(client, make_clip(str(tmp_path / "a.mp4"), [("tone", 4)]))
    put_project(client, selection={"start": 3, "end": 3})
    j = wait_job(client, client.post("/api/export", json={}).json()["job"])
    assert j["state"] == "error" and j["error"]["code"] == "selection_invalid"


def test_exports_path_traversal_rejected(client):
    assert client.get("/exports/..%2f..%2fetc%2fpasswd").status_code == 404
    assert client.get("/exports/nothere.mp4").status_code == 404


def test_job_cancel_via_runner():
    runner = JobRunner()
    started = threading.Event()

    def work(progress, cancel):
        started.set()
        while not cancel.is_set():
            time.sleep(0.01)
        from core.media import Cancelled
        raise Cancelled()

    jid = runner.submit(work, "w")
    assert started.wait(2)
    runner.cancel(jid)
    for _ in range(200):
        if runner.get(jid)["state"] == "cancelled":
            break
        time.sleep(0.01)
    assert runner.get(jid)["state"] == "cancelled"


def test_cancel_unknown_job_404(client):
    assert client.post("/api/jobs/nope/cancel").status_code == 404


def test_clear_temp_keeps_referenced_proxy(client, tmp_path):
    out = add_clip(client, make_clip(str(tmp_path / "a.mkv"), SPEC))
    wait_job(client, out["job"])
    proxy = get_project(client)["clips"][0]["proxy_path"]
    orphan = os.path.join(os.path.dirname(proxy), "orphan.mp4")
    open(orphan, "wb").write(b"x" * 10)
    assert client.post("/api/clear-temp").status_code == 200
    assert os.path.exists(proxy) and not os.path.exists(orphan)


def test_server_binds_localhost_only(monkeypatch, tmp_path):
    captured = {}
    monkeypatch.setattr(app_module.uvicorn, "run", lambda app, **kw: captured.update(kw))
    monkeypatch.setenv("VIDCUT_HOME", str(tmp_path))
    app_module.run_server(port=4321)
    assert captured["host"] == "127.0.0.1" and captured["port"] == 4321


def test_project_includes_presets_with_safe_zones(client):
    presets = client.get("/api/project").json()["presets"]
    assert presets["tiktok"]["width"] == 1080 and presets["tiktok"]["height"] == 1920
    assert presets["youtube"]["width"] == 1920
    assert set(presets["tiktok"]["safe_zone"]) == {"top", "bottom", "left", "right"}
    assert presets["tiktok"]["style_overrides"] == {"size": 72, "default_y": 0.70}


def test_bundled_fonts_are_served_for_the_preview(client):
    r = client.get("/fonts/Sarabun-Regular.ttf")
    assert r.status_code == 200 and len(r.content) > 10000
    assert client.get("/fonts/nothere.ttf").status_code == 404


def png_size(data: bytes) -> tuple[int, int]:
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")


@pytest.mark.skipif(not has_libass(), reason="ffmpeg without libass")
def test_preview_frame_returns_png_with_preset_dimensions(client, tmp_path):
    add_clip(client, make_clip(str(tmp_path / "a.mp4"), [("tone", 4)]))
    r = client.post("/api/preview-frame", json={"t": 1.0})
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"
    assert png_size(r.content) == (1080, 1920)
    put_project(client, preset="youtube")
    assert png_size(client.post("/api/preview-frame", json={"t": 1.0}).content) == (1920, 1080)


def test_preview_frame_without_clips_is_thai_error(client):
    r = client.post("/api/preview-frame", json={"t": 0})
    assert r.status_code == 400 and r.json()["error"]["code"] == "no_clips"


@pytest.mark.skipif(not has_libass(), reason="ffmpeg without libass")
def test_export_result_reports_output_folder(client, tmp_path):
    add_clip(client, make_clip(str(tmp_path / "a.mp4"), [("tone", 4)]))
    put_project(client, selection={"start": 0, "end": 2})
    j = wait_job(client, client.post("/api/export", json={}).json()["job"])
    assert os.path.isdir(j["result"]["dir"]) and os.path.exists(os.path.join(j["result"]["dir"], j["result"]["video"]))



# ---- review fixes: localhost hardening, stale saves, job safety --------------------------------
def test_foreign_host_header_is_rejected(client):
    """DNS rebinding: a page on evil.example resolving to 127.0.0.1 must not reach the API."""
    r = client.get("/api/project", headers={"Host": "evil.example:8765"})
    assert r.status_code == 400


def test_cross_origin_post_is_rejected(client):
    r = client.post("/api/clear-temp", headers={"Origin": "http://evil.example"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "forbidden_origin"


def test_same_origin_post_is_allowed(client):
    assert client.post("/api/clear-temp", headers={"Origin": "http://127.0.0.1:8765"}).status_code == 200
    assert client.post("/api/clear-temp", headers={"Origin": "http://localhost:8765"}).status_code == 200


def test_put_cannot_repoint_a_clip_at_another_file(client, tmp_path):
    src = make_clip(str(tmp_path / "a.mp4"), SPEC)
    cid = add_clip(client, src)["clip"]["id"]
    secret = tmp_path / "secret.txt"
    secret.write_text("do not serve me")
    p = get_project(client)
    p["clips"][0].update(path=str(secret), proxy_path=str(secret), duration=1.0)
    assert client.put("/api/project", json=p).status_code == 200
    got = get_project(client)["clips"][0]
    assert got["path"] == src and got["proxy_path"] is None and got["duration"] > 3
    body = client.get(f"/media/{cid}").content
    assert b"do not serve me" not in body and len(body) == os.path.getsize(src)


def test_put_cannot_add_clips(client, tmp_path):
    p = get_project(client)
    p["clips"].append({"id": "evil", "path": str(tmp_path / "x"), "duration": 1, "width": 1, "height": 1,
                       "fps": 25, "has_audio": True, "keeps": [], "proxy_path": None,
                       "framing": {"mode": "blur_fit", "crop_center_x": 0.5}})
    assert client.put("/api/project", json=p).status_code == 200
    assert get_project(client)["clips"] == []


def test_put_keeps_client_owned_fields(client, tmp_path):
    add_clip(client, make_clip(str(tmp_path / "a.mp4"), SPEC))
    p = get_project(client)
    p["clips"][0]["keeps"] = [{"start": 0.5, "end": 1.5, "enabled": False}]
    p["clips"][0]["framing"] = {"mode": "crop", "crop_center_x": 0.2}
    p["subtitles"] = []
    assert client.put("/api/project", json=p).status_code == 200
    got = get_project(client)["clips"][0]
    assert got["keeps"] == [{"start": 0.5, "end": 1.5, "enabled": False}] and got["framing"]["mode"] == "crop"


def test_job_results_bump_rev_and_stale_put_is_rejected(client, tmp_path):
    cid = add_clip(client, make_clip(str(tmp_path / "a.mp4"), SPEC))["clip"]["id"]
    stale = get_project(client)
    j = wait_job(client, client.post(f"/api/clips/{cid}/silence", json={}).json()["job"])
    assert j["state"] == "done"
    fresh = get_project(client)
    assert fresh["rev"] > stale["rev"]
    r = client.put("/api/project", json=stale)  # a page that never saw the job's result
    assert r.status_code == 409 and r.json()["error"]["code"] == "project_stale"
    assert get_project(client)["clips"][0]["keeps"] == fresh["clips"][0]["keeps"]
    assert client.put("/api/project", json=fresh).status_code == 200


def test_project_lists_the_offered_fonts(client):
    from core.fonts import FONT_FILES
    assert set(client.get("/api/project").json()["fonts"]) == set(FONT_FILES)


def test_clear_temp_is_refused_while_a_job_runs(client):
    release = threading.Event()
    jid = client.app.state.st.jobs.submit(lambda progress, cancel: release.wait(10) and {}, "blocker")
    for _ in range(100):
        if client.app.state.st.jobs.get(jid)["state"] == "running":
            break
        time.sleep(0.02)
    r = client.post("/api/clear-temp")
    assert r.status_code == 409 and r.json()["error"]["code"] == "busy"
    release.set()
    wait_job(client, jid)
    assert client.post("/api/clear-temp").status_code == 200


def test_clear_temp_survives_a_file_it_cannot_delete(client, tmp_path, monkeypatch):
    st = client.app.state.st
    os.makedirs(st.proxies, exist_ok=True)
    stuck = os.path.join(st.proxies, "stuck.mp4")
    open(stuck, "wb").write(b"x")
    real_remove = os.remove
    monkeypatch.setattr(os, "remove", lambda p: (_ for _ in ()).throw(PermissionError("in use")) if p == os.path.abspath(stuck) else real_remove(p))
    r = client.post("/api/clear-temp")
    assert r.status_code == 200 and r.json()["skipped"] == 1


def test_proxy_jobs_do_not_starve_other_jobs():
    runner = JobRunner(workers=1, proxy_workers=1)
    release = threading.Event()
    slow = [runner.submit(lambda progress, cancel: release.wait(10) and {}, "proxy", pool="proxy") for _ in range(2)]
    quick = runner.submit(lambda progress, cancel: {"ok": True}, "silence")
    for _ in range(200):
        if runner.get(quick)["state"] == "done":
            break
        time.sleep(0.01)
    assert runner.get(quick)["state"] == "done"
    assert runner.get(slow[1])["state"] == "queued"  # waits its turn, and says so
    release.set()


# ---- SRT import (YouTube captions) -------------------------------------------------------------
SRT = ("1\n00:00:00,500 --> 00:00:02,000\nสวัสดีครับทุกคน\n\n"
       "2\n00:00:02,200 --> 00:00:03,800\nวันนี้เรามาตัดต่อ\n")


def import_srt(client, cid, **kw):
    body = {"clip_id": cid, "srt_text": SRT, "only_selection": False}
    body.update(kw)
    return client.post("/api/subtitles/import-srt", json=body)


def test_import_srt_creates_source_anchored_subtitles(client, tmp_path):
    cid = add_clip(client, make_clip(str(tmp_path / "a.mp4"), [("tone", 4)]))["clip"]["id"]
    r = import_srt(client, cid)
    assert r.status_code == 200 and r.json()["count"] >= 1
    subs = get_project(client)["subtitles"]
    assert all(s["clip_id"] == cid for s in subs)
    assert "".join(s["text"] for s in subs).replace("\n", "") == "สวัสดีครับทุกคนวันนี้เรามาตัดต่อ"
    assert subs[0]["src_start"] == pytest.approx(0.5, abs=0.01)


def test_import_srt_replaces_only_that_clips_subtitles(client, tmp_path):
    a = add_clip(client, make_clip(str(tmp_path / "a.mp4"), [("tone", 4)]))["clip"]["id"]
    b = add_clip(client, make_clip(str(tmp_path / "b.mp4"), [("tone", 4)]))["clip"]["id"]
    keep = {"id": "keepme", "clip_id": b, "src_start": 1.0, "src_end": 2.0, "text": "ของคลิป B", "x": None, "y": None}
    old = {"id": "old", "clip_id": a, "src_start": 1.0, "src_end": 2.0, "text": "ซับเก่า", "x": None, "y": None}
    put_project(client, subtitles=[old, keep])
    rev = get_project(client)["rev"]
    assert import_srt(client, a).status_code == 200
    subs = get_project(client)["subtitles"]
    assert [s["id"] for s in subs if s["clip_id"] == b] == ["keepme"]
    assert not any(s["id"] == "old" for s in subs)
    assert get_project(client)["rev"] > rev


def test_import_srt_only_selection_needs_a_selection(client, tmp_path):
    cid = add_clip(client, make_clip(str(tmp_path / "a.mp4"), [("tone", 4)]))["clip"]["id"]
    r = import_srt(client, cid, only_selection=True)
    assert r.status_code == 400 and r.json()["error"]["code"] == "no_selection"


def test_import_srt_only_selection_keeps_cues_in_range(client, tmp_path):
    cid = add_clip(client, make_clip(str(tmp_path / "a.mp4"), [("tone", 4)]))["clip"]["id"]
    put_project(client, selection={"start": 0.0, "end": 2.1})
    assert import_srt(client, cid, only_selection=True).status_code == 200
    text = "".join(s["text"] for s in get_project(client)["subtitles"]).replace("\n", "")
    assert text == "สวัสดีครับทุกคน"


def test_import_srt_offset_shifts_times(client, tmp_path):
    cid = add_clip(client, make_clip(str(tmp_path / "a.mp4"), [("tone", 4)]))["clip"]["id"]
    import_srt(client, cid, offset=0.25)
    assert get_project(client)["subtitles"][0]["src_start"] == pytest.approx(0.75, abs=0.01)


@pytest.mark.parametrize("srt", ["", "this is not subtitles"])
def test_import_srt_of_a_non_srt_file_is_a_thai_error(client, tmp_path, srt):
    cid = add_clip(client, make_clip(str(tmp_path / "a.mp4"), [("tone", 4)]))["clip"]["id"]
    r = import_srt(client, cid, srt_text=srt)
    assert r.status_code == 400 and r.json()["error"]["code"] == "srt_empty"
    assert r.json()["error"]["message"] and r.json()["error"]["message"].isascii()


def test_import_srt_that_matches_nothing_says_so(client, tmp_path):
    cid = add_clip(client, make_clip(str(tmp_path / "a.mp4"), [("tone", 4)]))["clip"]["id"]
    r = import_srt(client, cid, offset=500.0)
    assert r.status_code == 400 and r.json()["error"]["code"] == "srt_no_match"
    assert get_project(client)["subtitles"] == []


def test_import_srt_for_an_unknown_clip_is_404(client):
    assert import_srt(client, "nope").status_code == 404


def test_put_saves_a_clip_role_and_falls_back_to_main_for_unknown_ones(client, tmp_path):
    add_clip(client, make_clip(str(tmp_path / "a.mp4"), SPEC))
    p = get_project(client)
    p["clips"][0]["role"] = "intro"
    assert client.put("/api/project", json=p).status_code == 200
    assert get_project(client)["clips"][0]["role"] == "intro"
    p = get_project(client)
    p["clips"][0]["role"] = "bogus"
    assert client.put("/api/project", json=p).status_code == 200
    assert get_project(client)["clips"][0]["role"] == "main"


@pytest.mark.skipif(not has_libass(), reason="ffmpeg without libass")
def test_export_job_joins_an_outro_clip(client, tmp_path):
    add_clip(client, make_clip(str(tmp_path / "main.mp4"), [("tone", 4)]))
    outro = add_clip(client, make_clip(str(tmp_path / "outro.mp4"), [("tone", 1.5)]))["clip"]["id"]
    p = get_project(client)
    next(c for c in p["clips"] if c["id"] == outro)["role"] = "outro"
    p["selection"] = {"start": 0, "end": 2}
    assert client.put("/api/project", json=p).status_code == 200
    j = wait_job(client, client.post("/api/export", json={}).json()["job"])
    assert j["state"] == "done", j
    out = os.path.join(j["result"]["dir"], j["result"]["video"])
    d = float(__import__("subprocess").run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", out],
                                           capture_output=True, text=True).stdout)
    assert d == pytest.approx(2 + 1.5, abs=0.15)


# ---- export options: estimate, folder, container ------------------------------------------------------
def export_settings(client, **kw):
    p = get_project(client)
    p["export"].update(kw)
    assert client.put("/api/project", json=p).status_code == 200


def test_estimate_reports_length_and_size(client, tmp_path):
    from core.encode import estimate_bytes
    from core.models import ExportSettings
    add_clip(client, make_clip(str(tmp_path / "a.mp4"), [("tone", 4)]))
    put_project(client, selection={"start": 0, "end": 2})
    r = client.post("/api/export/estimate").json()
    assert r["seconds"] == pytest.approx(2.0, abs=0.05)
    # the test clip is a few kbps, so the quality level is capped to its share of the source bitrate
    assert r["source_kbps"] is not None and r["video_kbps"] == min(5000, max(800, round(r["source_kbps"] * 0.8)))
    assert r["bytes"] == estimate_bytes(ExportSettings(), "tiktok", r["seconds"], r["source_kbps"])
    assert r["audio_kbps"] == 160


def test_estimate_follows_the_chosen_target_size(client, tmp_path):
    add_clip(client, make_clip(str(tmp_path / "a.mp4"), [("tone", 4)]))
    put_project(client, selection={"start": 0, "end": 2})
    export_settings(client, quality="custom", target_mb=1.0)
    assert client.post("/api/export/estimate").json()["bytes"] == pytest.approx(1048576, rel=0.02)


def test_estimate_counts_intro_and_outro(client, tmp_path):
    add_clip(client, make_clip(str(tmp_path / "main.mp4"), [("tone", 4)]))
    intro = add_clip(client, make_clip(str(tmp_path / "intro.mp4"), [("tone", 1.5)]))["clip"]["id"]
    p = get_project(client)
    next(c for c in p["clips"] if c["id"] == intro)["role"] = "intro"
    p["selection"] = {"start": 0, "end": 2}
    assert client.put("/api/project", json=p).status_code == 200
    assert client.post("/api/export/estimate").json()["seconds"] == pytest.approx(3.5, abs=0.05)


def test_estimate_for_an_unusable_selection_is_a_thai_error(client, tmp_path):
    add_clip(client, make_clip(str(tmp_path / "a.mp4"), [("tone", 4)]))
    put_project(client, selection={"start": 3, "end": 3})
    r = client.post("/api/export/estimate")
    assert r.status_code == 400 and r.json()["error"]["code"] == "selection_invalid"


def test_export_folder_by_path_is_created_and_remembered(client, tmp_path):
    target = tmp_path / "ปลายทาง ใหม่" / "shorts"
    r = client.post("/api/export-folder", json={"path": str(target)})
    assert r.status_code == 200 and target.is_dir()
    assert get_project(client)["export"]["out_dir"] == str(target)
    assert client.post("/api/export-folder", json={"path": ""}).status_code == 200
    assert get_project(client)["export"]["out_dir"] == ""


def test_export_folder_must_be_a_folder_we_can_write_to(client, tmp_path):
    f = tmp_path / "file.txt"
    f.write_text("x")
    r = client.post("/api/export-folder", json={"path": str(f)})
    assert r.status_code == 400 and r.json()["error"]["code"] == "folder_unwritable"


def test_export_folder_pick_uses_the_override_env(client, tmp_path, monkeypatch):
    monkeypatch.setenv("VIDCUT_PICK_FOLDER_OVERRIDE", str(tmp_path / "picked"))
    assert client.post("/api/export-folder/pick").json()["out_dir"] == str(tmp_path / "picked")


def test_put_cannot_change_the_export_folder(client, tmp_path):
    client.post("/api/export-folder", json={"path": str(tmp_path / "mine")})
    export_settings(client, out_dir="/etc", container="mkv")
    got = get_project(client)["export"]
    assert got["out_dir"] == str(tmp_path / "mine") and got["container"] == "mkv"


@pytest.mark.skipif(not has_libass(), reason="ffmpeg without libass")
def test_export_job_uses_the_chosen_container_and_folder(client, tmp_path):
    add_clip(client, make_clip(str(tmp_path / "a.mp4"), [("tone", 4)]))
    put_project(client, selection={"start": 0, "end": 2})
    client.post("/api/export-folder", json={"path": str(tmp_path / "out here")})
    export_settings(client, container="mkv", quality="small")
    j = wait_job(client, client.post("/api/export", json={}).json()["job"])
    assert j["state"] == "done", j
    assert j["result"]["video"].endswith(".mkv") and j["result"]["dir"] == str(tmp_path / "out here")
    assert j["result"]["downloadable"] is False
    assert os.path.exists(os.path.join(j["result"]["dir"], j["result"]["video"]))


def test_cuts_confirmed_is_client_owned_and_reset_by_detection(client, tmp_path):
    path = make_clip(str(tmp_path / "a.mp4"), SPEC)
    added = add_clip(client, path)
    clip_id = added["clip"]["id"]
    proj = get_project(client)
    proj["clips"][0]["cuts_confirmed"] = True
    assert client.put("/api/project", json=proj).status_code == 200
    assert get_project(client)["clips"][0]["cuts_confirmed"] is True
    job = client.post(f"/api/clips/{clip_id}/silence", json={}).json()["job"]
    assert wait_job(client, job)["state"] == "done"
    assert get_project(client)["clips"][0]["cuts_confirmed"] is False


# ---- overlays (logo / photo) -------------------------------------------------------------------------
def _logo(tmp_path, name="logo.png"):
    import subprocess
    p = str(tmp_path / name)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=red:s=64x32", "-frames:v", "1", p], check=True)
    return p


def test_overlay_add_edit_serve_delete(client, tmp_path):
    r = client.post("/api/overlays", json={"path": _logo(tmp_path)})
    assert r.status_code == 200
    o = r.json()["overlay"]
    assert (r.json()["width"], r.json()["height"]) == (64, 32)
    assert client.get(f"/overlay-media/{o['id']}").status_code == 200
    proj = get_project(client)
    proj["overlays"][0].update(x=0.3, y=5, width=0.4, opacity=0.5, start=1.0, end=2.0, path="/etc/passwd")
    assert client.put("/api/project", json=proj).status_code == 200
    got = get_project(client)["overlays"][0]
    assert (got["x"], got["y"], got["width"], got["opacity"], got["start"], got["end"]) == (0.3, 1.0, 0.4, 0.5, 1.0, 2.0)
    assert got["path"] == o["path"]  # the page can't repoint the image at another file
    assert client.delete(f"/api/overlays/{o['id']}").status_code == 200
    assert get_project(client)["overlays"] == []
    assert client.delete(f"/api/overlays/{o['id']}").status_code == 404


def test_overlay_rejects_non_images_and_missing_files(client, tmp_path):
    txt = tmp_path / "a.txt"
    txt.write_text("hi")
    assert client.post("/api/overlays", json={"path": str(txt)}).json()["error"]["code"] == "not_an_image"
    assert client.post("/api/overlays", json={"path": str(tmp_path / "nope.png")}).status_code == 404


def test_overlay_picker_override(client, tmp_path, monkeypatch):
    monkeypatch.setenv("VIDCUT_PICK_IMAGE_OVERRIDE", _logo(tmp_path))
    assert client.post("/api/overlays/pick").json()["overlay"]["path"].endswith("logo.png")


# ---- episodes ----------------------------------------------------------------------------------------------
def _episode_project(client, tmp_path):
    main = add_clip(client, make_clip(str(tmp_path / "main.mp4"), [("tone", 60)], size="320x180"))["clip"]["id"]
    i1 = add_clip(client, make_clip(str(tmp_path / "i1.mp4"), [("tone", 2)], size="320x180"))["clip"]["id"]
    i2 = add_clip(client, make_clip(str(tmp_path / "i2.mp4"), [("tone", 3)], size="320x180"))["clip"]["id"]
    out = add_clip(client, make_clip(str(tmp_path / "out.mp4"), [("tone", 1)], size="320x180"))["clip"]["id"]
    p = get_project(client)
    roles = {i1: "intro", i2: "intro", out: "outro"}
    for c in p["clips"]:
        c["role"] = roles.get(c["id"], "main")
    assert client.put("/api/project", json=p).status_code == 200
    return main, i1, i2, out


def test_episode_plan_splits_by_size_and_assigns_intros(client, tmp_path):
    _, i1, i2, _ = _episode_project(client, tmp_path)
    r = client.post("/api/episodes/plan", json={"max_mb": 5}).json()
    eps = r["episodes"]
    assert len(eps) == 2 and r["intro_clips"] == 2 and not r["intro_reused"]
    assert eps[0]["start"] == 0 and eps[0]["end"] == eps[1]["start"] and eps[1]["end"] == pytest.approx(60, abs=0.5)
    assert [e["intro_clip_id"] for e in eps] == [i1, i2]
    assert all(e["est_bytes"] <= 5 * 1048576 for e in eps)


def test_episode_limit_too_small_is_a_clear_error(client, tmp_path):
    _episode_project(client, tmp_path)
    assert client.post("/api/episodes/plan", json={"max_mb": 1}).json()["error"]["code"] == "episode_limit_too_small"


def test_episode_export_writes_numbered_files_each_with_its_own_intro_and_the_outro(client, tmp_path):
    _episode_project(client, tmp_path)
    out = str(tmp_path / "eps")
    assert client.post("/api/export-folder", json={"path": out}).status_code == 200
    job = client.post("/api/episodes/export", json={"max_mb": 5}).json()["job"]
    j = wait_job(client, job, timeout=200)
    assert j["state"] == "done", j
    files = j["result"]["files"]
    assert [f["video"] for f in files] == ["main_tiktok_EP01.mp4", "main_tiktok_EP02.mp4"]
    assert not any(f["over_limit"] for f in files)
    durs = [media.probe(os.path.join(out, f["video"]))["duration"] for f in files]
    assert durs[0] == pytest.approx(30 + 2 + 1, abs=0.6) and durs[1] == pytest.approx(30 + 3 + 1, abs=0.6)


# ---- highlights ---------------------------------------------------------------------------------------------
def _subs_project(client, tmp_path, texts):
    cid = add_clip(client, make_clip(str(tmp_path / "h.mp4"), [("tone", 60)], size="320x180"))["clip"]["id"]
    subs = [{"id": f"s{i}", "clip_id": cid, "src_start": i * 3.0, "src_end": i * 3.0 + 2.5, "text": t, "x": None, "y": None}
            for i, t in enumerate(texts)]
    put_project(client, subtitles=subs)


def test_highlights_need_subtitles(client, tmp_path):
    add_clip(client, make_clip(str(tmp_path / "h.mp4"), [("tone", 5)], size="320x180"))
    assert client.post("/api/highlights", json={}).json()["error"]["code"] == "no_subtitles"
    assert client.get("/api/highlights/transcript").json()["error"]["code"] == "no_subtitles"


def test_highlights_find_the_scolding_part_and_export_a_transcript(client, tmp_path):
    texts = ["เรียนเรื่องภาษี"] * 8 + ["ไอ้โง่ ไม่ได้เรื่อง", "ขี้เกียจ น่าอาย"] + ["เรียนต่อ"] * 8
    _subs_project(client, tmp_path, texts)
    r = client.post("/api/highlights", json={"min_s": 15, "max_s": 30}).json()
    scold = [c for c in r["candidates"] if c["category"] == "scold"]
    assert scold and scold[0]["start"] <= 24 and scold[0]["end"] >= 30 and "scold" in r["lexicon"]
    t = client.get("/api/highlights/transcript").json()
    assert t["lines"] == len(texts) and "[00:24]" in t["text"]


# ---- captions for an original video, applied to its cut version ------------------------------------------------
def test_export_writes_a_manifest_next_to_the_video(client, tmp_path):
    from core.export import manifest_path
    add_clip(client, make_clip(str(tmp_path / "m.mp4"), [("tone", 4)], size="320x180"))
    out = str(tmp_path / "o")
    client.post("/api/export-folder", json={"path": out})
    put_project(client, selection={"start": 1, "end": 3})
    j = wait_job(client, client.post("/api/export").json()["job"], timeout=120)
    assert j["state"] == "done"
    mf = json.loads(open(manifest_path(os.path.join(out, j["result"]["video"])), encoding="utf-8").read())
    assert mf["version"] == 1 and mf["sources"][0]["name"] == "m.mp4" and mf["sources"][0]["role"] == "main"
    piece = mf["sources"][0]["pieces"][0]
    assert piece["src_start"] == pytest.approx(1.0, abs=0.05) and piece["out_start"] == 0.0
    assert piece["src_end"] == pytest.approx(3.0, abs=0.1)


def test_cut_manifest_endpoint_finds_the_file_next_to_the_clip(client, tmp_path):
    path = make_clip(str(tmp_path / "cutvideo.mp4"), [("tone", 5)], size="320x180")
    cid = add_clip(client, path)["clip"]["id"]
    assert client.get(f"/api/clips/{cid}/cut-manifest").json() == {"found": False}
    (tmp_path / "cutvideo.vidcut.json").write_text(json.dumps({"version": 1, "video": "cutvideo.mp4", "sources": [
        {"name": "intro.mp4", "role": "intro", "pieces": [{"src_start": 0, "src_end": 2, "out_start": 0}]},
        {"name": "orig.mp4", "role": "main", "pieces": [{"src_start": 100, "src_end": 103, "out_start": 2}]}]}), encoding="utf-8")
    r = client.get(f"/api/clips/{cid}/cut-manifest").json()
    assert r["found"] and r["sources"][0]["name"] == "orig.mp4"  # the main source comes first
    (tmp_path / "cutvideo.vidcut.json").write_text("{not json", encoding="utf-8")
    assert client.get(f"/api/clips/{cid}/cut-manifest").json()["found"] is False


def test_import_srt_through_a_cut_map_moves_cues_onto_the_cut_clip(client, tmp_path):
    cid = add_clip(client, make_clip(str(tmp_path / "cut.mp4"), [("tone", 20)], size="320x180"))["clip"]["id"]
    srt = ("1\n00:01:40,500 --> 00:01:43,000\nสวัสดีครับทุกคน\n\n2\n00:03:00,000 --> 00:03:02,000\nนี่อยู่ในช่วงที่ถูกตัดออก\n\n"
           "3\n00:02:00,000 --> 00:02:03,000\nวันนี้เรามาตัดต่อ\n")
    pieces = [{"src_start": 100.0, "src_end": 110.0, "out_start": 0.0}, {"src_start": 120.0, "src_end": 130.0, "out_start": 10.0}]
    r = client.post("/api/subtitles/import-srt", json={"clip_id": cid, "srt_text": srt, "only_selection": False, "pieces": pieces})
    assert r.status_code == 200, r.text
    subs = get_project(client)["subtitles"]
    text = "".join(s["text"].replace("\n", "") for s in subs)
    assert "สวัสดีครับทุกคน" in text and "วันนี้เรามาตัดต่อ" in text and "ถูกตัดออก" not in text
    first = min(subs, key=lambda s: s["src_start"])
    assert first["src_start"] == pytest.approx(0.5, abs=0.3)
    last = max(subs, key=lambda s: s["src_start"])
    assert last["src_start"] == pytest.approx(10.0, abs=0.3)


def test_align_endpoint_recovers_the_cut_map_from_audio(client, tmp_path, monkeypatch):
    import subprocess
    import numpy as np
    from tests.test_align import cut_of, speechlike, write_wav
    orig_audio = speechlike(100, 11)
    ranges = [(10.0, 40.0), (55.0, 90.0)]
    write_wav(tmp_path / "o.wav", orig_audio)
    write_wav(tmp_path / "c.wav", cut_of(orig_audio, ranges))

    def video(wav, out, secs):
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"color=c=black:s=160x90:r=10:d={secs}", "-i", str(wav),
                        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(out)], check=True)
    video(tmp_path / "o.wav", tmp_path / "orig.mp4", 100)
    video(tmp_path / "c.wav", tmp_path / "cutv.mp4", 65)
    cid = add_clip(client, str(tmp_path / "cutv.mp4"))["clip"]["id"]
    j = wait_job(client, client.post(f"/api/clips/{cid}/align", json={"original_path": str(tmp_path / "orig.mp4")}).json()["job"])
    assert j["state"] == "done", j
    ps = j["result"]["pieces"]
    assert len(ps) == 2 and ps[0]["src_start"] == pytest.approx(10.0, abs=0.3) and ps[1]["src_start"] == pytest.approx(55.0, abs=0.3)
    assert ps[1]["out_start"] == pytest.approx(30.0, abs=0.3) and j["result"]["coverage"] > 0.9


def test_align_with_an_unrelated_original_is_a_clear_error(client, tmp_path):
    import subprocess
    from tests.test_align import speechlike, write_wav
    write_wav(tmp_path / "a.wav", speechlike(40, 21))
    write_wav(tmp_path / "b.wav", speechlike(60, 22))
    for n, secs in (("a", 40), ("b", 60)):
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"color=c=black:s=160x90:r=10:d={secs}", "-i", str(tmp_path / f"{n}.wav"),
                        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(tmp_path / f"{n}.mp4")], check=True)
    cid = add_clip(client, str(tmp_path / "a.mp4"))["clip"]["id"]
    j = wait_job(client, client.post(f"/api/clips/{cid}/align", json={"original_path": str(tmp_path / "b.mp4")}).json()["job"])
    assert j["state"] == "error" and j["error"]["code"] == "align_failed"


def test_episode_export_uses_the_intro_chosen_for_each_episode(client, tmp_path):
    _, i1, i2, _ = _episode_project(client, tmp_path)
    out = str(tmp_path / "eps2")
    client.post("/api/export-folder", json={"path": out})
    bad = client.post("/api/episodes/export", json={"max_mb": 5, "intro_ids": [i1]}).json()
    assert bad["error"]["code"] == "intro_choice_invalid"
    plan = client.post("/api/episodes/plan", json={"max_mb": 5}).json()
    assert [c["name"] for c in plan["intros"]] == ["i1.mp4", "i2.mp4"]
    j = wait_job(client, client.post("/api/episodes/export", json={"max_mb": 5, "intro_ids": [i2, i1]}).json()["job"], timeout=200)
    assert j["state"] == "done", j
    durs = [media.probe(os.path.join(out, f["video"]))["duration"] for f in j["result"]["files"]]
    assert durs[0] == pytest.approx(30 + 3 + 1, abs=0.6) and durs[1] == pytest.approx(30 + 2 + 1, abs=0.6)


def test_rewrap_endpoint_reflows_all_subtitles_and_validates(client, tmp_path):
    cid = add_clip(client, make_clip(str(tmp_path / "w.mp4"), [("tone", 20)], size="320x180"))["clip"]["id"]
    text = "สวัสดีครับทุกคนวันนี้เรามาตัดต่อวิดีโอกันนะครับ"
    put_project(client, subtitles=[{"id": "a", "clip_id": cid, "src_start": 0, "src_end": 6, "text": text, "x": None, "y": None, "scale": None}])
    r = client.post("/api/subtitles/rewrap", json={"max_chars": 8, "max_lines": 1}).json()
    assert r["before"] == 1 and r["after"] > 1
    subs = get_project(client)["subtitles"]
    assert "".join(s["text"] for s in subs) == text and subs[0]["src_start"] == 0 and subs[-1]["src_end"] == 6
    assert client.post("/api/subtitles/rewrap", json={"max_chars": 2, "max_lines": 1}).json()["error"]["code"] == "rewrap_invalid"
    assert client.post("/api/subtitles/rewrap", json={"max_chars": "x"}).json()["error"]["code"] == "rewrap_invalid"
