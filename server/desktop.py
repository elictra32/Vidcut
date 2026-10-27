"""Run Vidcut like an ordinary desktop program: no console window, its own browser window, and it quits by itself once
that window is closed (unless an export is still running, which it finishes first).

Start with `pythonw -m server.desktop` (see Vidcut.vbs). A second launch just opens another window on the running one."""
import json
import os
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser

HOST = "127.0.0.1"
# (the environment variables are only for the tests)
GRACE_S = float(os.environ.get("VIDCUT_GRACE_S", 180.0))              # no ping for this long: the window is gone (a minimised window pings only about once a minute)
BYE_GRACE_S = float(os.environ.get("VIDCUT_BYE_GRACE_S", 8.0))        # a page said goodbye; a reload pings again in a second or two
STARTUP_GRACE_S = float(os.environ.get("VIDCUT_STARTUP_GRACE_S", 180.0))  # nobody ever opened a page after launching
CHECK_S = float(os.environ.get("VIDCUT_CHECK_S", 3.0))


def should_exit(now: float, started: float, last_seen: float | None, bye_at: float | None, busy: bool) -> bool:
    """The server's decision to quit. Pure, so it can be tested without a clock or a server."""
    if busy:
        return False  # finish the export that is running, then go
    if last_seen is None:
        return now - started > STARTUP_GRACE_S
    if bye_at is not None and bye_at >= last_seen:
        return now - bye_at > BYE_GRACE_S
    return now - last_seen > GRACE_S


def server_url(port: int) -> str:
    return f"http://{HOST}:{port}"


def already_running(port: int, timeout: float = 1.5) -> bool:
    try:
        with urllib.request.urlopen(server_url(port) + "/api/ping", timeout=timeout) as r:
            return json.load(r).get("app") == "vidcut"
    except Exception:  # noqa: BLE001 - anything wrong means "not (usably) running"
        return False


def app_browser_candidates(env: dict | None = None) -> list[str]:
    env = os.environ if env is None else env
    roots = [env.get(k) for k in ("PROGRAMFILES(X86)", "PROGRAMFILES", "LOCALAPPDATA") if env.get(k)]
    rel = [r"Microsoft\Edge\Application\msedge.exe", r"Google\Chrome\Application\chrome.exe", r"BraveSoftware\Brave-Browser\Application\brave.exe"]
    return [os.path.join(r, p) for p in rel for r in roots]


def open_window(url: str, env: dict | None = None) -> None:
    """A browser window without tabs or address bar (Edge/Chrome app mode); the default browser if neither exists."""
    if os.environ.get("VIDCUT_NO_BROWSER") == "1":
        return
    for exe in app_browser_candidates(env):
        if os.path.isfile(exe):
            subprocess.Popen([exe, f"--app={url}", "--window-size=1600,1000"], close_fds=True)
            return
    webbrowser.open(url)


def refresh_windows_path() -> None:
    """Explorer hands us the PATH it had at logon; winget installs (ffmpeg) update the registry only. Re-read it."""
    if os.name != "nt":
        return
    try:
        import winreg
        parts = [os.environ.get("PATH", "")]
        for hive, sub in ((winreg.HKEY_CURRENT_USER, "Environment"),
                          (winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment")):
            try:
                with winreg.OpenKey(hive, sub) as k:
                    parts.append(os.path.expandvars(winreg.QueryValueEx(k, "Path")[0]))
            except OSError:
                pass
        parts.append(os.path.join(os.environ.get("LOCALAPPDATA", ""), r"Microsoft\WinGet\Links"))
        os.environ["PATH"] = os.pathsep.join(p for p in parts if p)
    except Exception:  # noqa: BLE001 - best effort: run.bat does the same job
        pass


def redirect_output(home: str) -> None:
    """pythonw has no console: send stdout/stderr to a log file (uvicorn writes to them)."""
    if sys.stdout is not None and sys.stderr is not None:
        return
    os.makedirs(home, exist_ok=True)
    log = open(os.path.join(home, "vidcut.log"), "a", encoding="utf-8", buffering=1)
    sys.stdout = sys.stdout or log
    sys.stderr = sys.stderr or log


def watch(server, st, is_busy) -> None:
    """Background thread: ask uvicorn to stop when the window is gone and nothing is running, or on /api/quit."""
    while not server.should_exit:
        time.sleep(CHECK_S)
        if st.quit_requested or should_exit(time.time(), st.started, st.last_seen, st.bye_at, is_busy()):
            st.save()
            server.should_exit = True


def main() -> None:
    import uvicorn

    from server.app import create_app, default_home

    port = int(os.environ.get("VIDCUT_PORT", "8765"))
    if already_running(port):
        open_window(server_url(port))
        return
    refresh_windows_path()
    os.environ.setdefault("PYTHONUTF8", "1")
    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
    redirect_output(default_home())
    app = create_app()
    st = app.state.st

    def busy() -> bool:
        snap = st.queue.snapshot()
        waiting = (not snap["paused"]) and any(i["state"] == "queued" for i in snap["items"])
        return st.jobs.active(ignore=("proxy",)) > 0 or snap["running"] or waiting

    server = uvicorn.Server(uvicorn.Config(app, host=HOST, port=port, log_level="warning"))
    threading.Thread(target=watch, args=(server, st, busy), daemon=True, name="vidcut-watch").start()
    if os.environ.get("VIDCUT_NO_BROWSER") != "1":
        threading.Timer(1.2, lambda: open_window(server_url(port))).start()
    server.run()
    st.queue.stop()


if __name__ == "__main__":
    main()
