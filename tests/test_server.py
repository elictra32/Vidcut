import json
import os
import threading
import time

import pytest
from fastapi.testclient import TestClient

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
    return TestClient(create_app(home=str(tmp_path / "home")))


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
    assert any("฀" <= ch <= "๿" for ch in err["message"])


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
    assert any("฀" <= ch <= "๿" for ch in j["error"]["message"])


@pytest.mark.skipif(not has_libass(), reason="ffmpeg without libass")
def test_export_job_produces_mp4_and_srt(client, tmp_path):
    add_clip(client, make_clip(str(tmp_path / "a.mp4"), [("tone", 4)]))
    put_project(client, selection={"start": 0, "end": 2})
    j = wait_job(client, client.post("/api/export", json={"preset": "youtube"}).json()["job"])
    assert j["state"] == "done", j
    mp4, srt = j["result"]["mp4"], j["result"]["srt"]
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
