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
