import json
import subprocess

import pytest

from tools import install_skills as inst


def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


@pytest.fixture
def remote(tmp_path):
    r = tmp_path / "remote"
    (r / "skills" / "a").mkdir(parents=True)
    (r / "skills" / "b").mkdir(parents=True)
    (r / "skills" / "notaskill").mkdir(parents=True)
    (r / "skills" / "a" / "SKILL.md").write_text("---\nname: a\n---\n")
    (r / "skills" / "b" / "SKILL.md").write_text("---\nname: b\n---\n")
    (r / "SKILL.md").write_text("root")
    (r / "scripts").mkdir()
    (r / "scripts" / "x.py").write_text("1")
    (r / "big").mkdir()
    (r / "big" / "blob").write_text("x")
    _git(r, "init", "-q")
    _git(r, "-c", "user.name=t", "-c", "user.email=t@t", "add", "-A")
    _git(r, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "c")
    sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=r, capture_output=True, text=True, check=True).stdout.strip()
    return r, sha


def test_glob_include_and_workspace(remote, tmp_path):
    r, sha = remote
    entry = {"id": "kit", "repo": str(r), "commit": sha,
             "skills": [{"src": "skills/*"}, {"src": ".", "dest": "root", "include": ["SKILL.md", "scripts"]}],
             "workspace": {"exclude": ["big"]}}
    skills, tp = tmp_path / "skills", tmp_path / "tp"
    inst.install_one(entry, skills, tp, log=lambda _m: None)
    assert sorted(p.name for p in skills.iterdir()) == ["a", "b", "root"]  # notaskill has no SKILL.md
    assert (skills / "root" / "scripts" / "x.py").exists() and not (skills / "root" / "big").exists()
    assert (tp / "kit" / "skills" / "a" / "SKILL.md").exists() and not (tp / "kit" / "big").exists()
    assert not (tp / "kit" / ".git").exists()


def test_reinstall_replaces(remote, tmp_path):
    r, sha = remote
    entry = {"id": "k", "repo": str(r), "commit": sha, "skills": [{"src": "skills/a", "dest": "a"}]}
    skills = tmp_path / "s"
    inst.install_one(entry, skills, tmp_path / "t", log=lambda _m: None)
    (skills / "a" / "stale.txt").write_text("old")
    inst.install_one(entry, skills, tmp_path / "t", log=lambda _m: None)
    assert not (skills / "a" / "stale.txt").exists()


def test_manifest_is_pinned_and_complete():
    entries = inst.load_manifest()
    assert len(entries) == 8
    for e in entries:
        assert len(e["commit"]) == 40 and e["repo"].startswith("https://github.com/")
        assert e.get("skills") or e.get("workspace")
    json.dumps(entries)


def test_unknown_id(capsys):
    assert inst.main(["install", "nope"]) == 2
