import ast
from pathlib import Path

from core import media

CORE = Path(__file__).resolve().parent.parent / "core"


def test_no_window_flag_is_set_on_windows_only(monkeypatch):
    monkeypatch.setattr(media.os, "name", "nt")
    assert media.no_window() == {"creationflags": 0x08000000}
    monkeypatch.setattr(media.os, "name", "posix")
    assert media.no_window() == {}


def test_every_subprocess_call_in_core_hides_the_console_window():
    """Without a console of its own (pythonw), each ffmpeg/ffprobe call would flash a terminal on Windows."""
    missing = []
    for path in sorted(CORE.glob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in ("run", "Popen", "check_output", "call") \
                    and isinstance(node.func.value, ast.Name) and node.func.value.id == "subprocess":
                hidden = any(k.arg is None and isinstance(k.value, ast.Call) and getattr(k.value.func, "id", "") == "no_window" for k in node.keywords)
                if not hidden:
                    missing.append(f"{path.name}:{node.lineno}")
    assert not missing, "subprocess calls without **no_window(): " + ", ".join(missing)
