import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

from server import desktop
from server.desktop import app_browser_candidates, should_exit

ROOT = Path(__file__).resolve().parent.parent


def test_should_exit_waits_for_a_window_then_for_it_to_go():
    g, b, s = desktop.GRACE_S, desktop.BYE_GRACE_S, desktop.STARTUP_GRACE_S
    # nobody has opened a page yet: give the browser time to start
    assert not should_exit(10, 0, None, None, busy=False)
    assert should_exit(s + 1, 0, None, None, busy=False)
    # a page is pinging
    assert not should_exit(100, 0, 99, None, busy=False)
    assert should_exit(100 + g + 1, 0, 100, None, busy=False)          # pings stopped (window gone)
    # a page said goodbye: leave soon, but not instantly (a reload says goodbye too, then pings again)
    assert not should_exit(105, 0, 100, 104, busy=False)
    assert should_exit(104 + b + 1, 0, 100, 104, busy=False)
    assert not should_exit(104 + b + 1, 0, 105, 104, busy=False)       # pinged again after the goodbye: it was a reload
    # a running export is finished first
    assert not should_exit(10_000, 0, 1, 2, busy=True)
    assert not should_exit(10_000, 0, None, None, busy=True)


def test_browser_candidates_prefer_edge_then_chrome():
    env = {"PROGRAMFILES(X86)": r"C:\PF86", "PROGRAMFILES": r"C:\PF", "LOCALAPPDATA": r"C:\Local"}
    c = app_browser_candidates(env)
    assert c[0].endswith(r"Microsoft\Edge\Application\msedge.exe") and r"C:\PF86" in c[0]
    assert any("chrome.exe" in p for p in c) and len(c) == 9


def test_open_window_does_nothing_when_browsers_are_disabled(monkeypatch):
    monkeypatch.setenv("VIDCUT_NO_BROWSER", "1")
    monkeypatch.setattr(desktop.subprocess, "Popen", lambda *a, **k: pytest.fail("must not start a browser"))
    monkeypatch.setattr(desktop.webbrowser, "open", lambda *a, **k: pytest.fail("must not start a browser"))
    desktop.open_window("http://127.0.0.1:1")


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def start(tmp_path, port, **extra):
    env = {**os.environ, "VIDCUT_HOME": str(tmp_path / "home"), "VIDCUT_PORT": str(port), "VIDCUT_NO_BROWSER": "1",
           "VIDCUT_CHECK_S": "0.2", **extra}
    return subprocess.Popen([sys.executable, "-m", "server.desktop"], cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)


def get(port, path, method="GET"):
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", method=method, data=b"" if method == "POST" else None,
                                 headers={"Origin": f"http://127.0.0.1:{port}"})
    with urllib.request.urlopen(req, timeout=3) as r:
        return r.read()


def wait_up(port, proc, timeout=20):
    end = time.time() + timeout
    while time.time() < end:
        if proc.poll() is not None:
            raise AssertionError("server exited early: " + proc.stdout.read().decode(errors="replace")[-800:])
        try:
            get(port, "/api/ping")
            return
        except Exception:  # noqa: BLE001
            time.sleep(0.1)
    raise AssertionError("server did not start")


def test_it_quits_by_itself_after_the_window_closes_and_a_second_launch_reuses_it(tmp_path):
    port = free_port()
    p = start(tmp_path, port, VIDCUT_BYE_GRACE_S="0.5", VIDCUT_GRACE_S="30", VIDCUT_STARTUP_GRACE_S="60")
    try:
        wait_up(port, p)
        assert b'"vidcut"' in get(port, "/api/ping")
        again = subprocess.run([sys.executable, "-m", "server.desktop"], cwd=ROOT, timeout=20, capture_output=True,
                               env={**os.environ, "VIDCUT_HOME": str(tmp_path / "home"), "VIDCUT_PORT": str(port), "VIDCUT_NO_BROWSER": "1"})
        assert again.returncode == 0 and p.poll() is None   # the second launch found the first and left
        get(port, "/api/bye", "POST")                       # the window was closed
        assert p.wait(timeout=15) == 0
    finally:
        if p.poll() is None:
            p.kill()


def test_a_reload_does_not_stop_it(tmp_path):
    port = free_port()
    p = start(tmp_path, port, VIDCUT_BYE_GRACE_S="1.5", VIDCUT_GRACE_S="30", VIDCUT_STARTUP_GRACE_S="60")
    try:
        wait_up(port, p)
        get(port, "/api/bye", "POST")
        time.sleep(0.4)
        get(port, "/api/ping")                              # the reloaded page pings again
        time.sleep(2.5)
        assert p.poll() is None
    finally:
        p.kill()


def test_quit_request_stops_it_and_saves(tmp_path):
    port = free_port()
    p = start(tmp_path, port, VIDCUT_GRACE_S="300", VIDCUT_STARTUP_GRACE_S="300")
    try:
        wait_up(port, p)
        get(port, "/api/ping")
        get(port, "/api/quit", "POST")
        assert p.wait(timeout=15) == 0
        assert (tmp_path / "home" / "project.json").exists()
    finally:
        if p.poll() is None:
            p.kill()


def test_it_gives_up_when_no_window_ever_opens(tmp_path):
    port = free_port()
    p = start(tmp_path, port, VIDCUT_STARTUP_GRACE_S="1.5")
    try:
        assert p.wait(timeout=20) == 0
    finally:
        if p.poll() is None:
            p.kill()
