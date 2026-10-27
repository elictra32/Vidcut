from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def bat(name):
    return (ROOT / name).read_bytes()


def test_bat_files_use_crlf_only():
    # cmd.exe mis-parses labels / multi-line blocks in LF-only batch files
    for name in ("setup.bat", "run.bat"):
        data = bat(name)
        assert b"\r\n" in data and b"\n" not in data.replace(b"\r\n", b""), name


def test_gitattributes_keeps_bat_crlf():
    assert "*.bat text eol=crlf" in (ROOT / ".gitattributes").read_text()


def test_setup_bat_installs_what_the_app_needs():
    s = bat("setup.bat").decode("utf-8")
    assert "Gyan.FFmpeg" in s and "winget" in s
    assert "-m venv" in s and "pip install -e ." in s
    assert "3.12" in s and "3.11" in s


def test_run_bat_starts_the_server_from_the_venv():
    s = bat("run.bat").decode("utf-8")
    assert r".venv\Scripts\python.exe" in s and "-m server.app" in s


def test_docs_exist():
    for name in ("README.md", "ARCHITECTURE.md"):
        assert (ROOT / name).stat().st_size > 1500, name


def test_setup_bat_refreshes_path_after_installing_ffmpeg():
    """winget changes PATH for NEW shells only; setup must re-read it instead of reporting a failed install."""
    s = bat("setup.bat").decode("utf-8")
    assert ":refreshpath" in s and r'HKCU\Environment' in s and r"WinGet\Links" in s
    install = s.index("winget install --id Gyan.FFmpeg -e --accept")
    assert "call :refreshpath" in s[install:s.index("where ffmpeg", install)]


def test_run_bat_refreshes_path_before_starting():
    s = bat("run.bat").decode("utf-8")
    assert ":refreshpath" in s and s.index("call :refreshpath") < s.index("-m server.app")


def test_desktop_launcher_runs_the_server_hidden_from_the_venv():
    s = bat("Vidcut.vbs").decode("ascii")
    assert b"\r\n" in bat("Vidcut.vbs") and b"\n" not in bat("Vidcut.vbs").replace(b"\r\n", b"")
    assert r".venv\Scripts\pythonw.exe" in s and "-m server.desktop" in s
    assert ", 0, False" in s            # window style 0 (hidden), do not wait
    assert "setup.bat" in s             # tells the user what to do when it is not installed


def test_setup_creates_the_shortcut_with_the_icon():
    assert "tools\\make_shortcut.ps1" in bat("setup.bat").decode("utf-8")
    ps = bat("tools/make_shortcut.ps1").decode("ascii")
    assert "wscript.exe" in ps and "Vidcut.vbs" in ps and "vidcut.ico" in ps
    assert "GetFolderPath(\"Desktop\")" in ps
    assert (ROOT / "assets" / "vidcut.ico").stat().st_size > 1000
    assert "*.vbs text eol=crlf" in (ROOT / ".gitattributes").read_text()
