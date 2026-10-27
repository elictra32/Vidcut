"""Install the 8 video-editing Claude skills listed in tools/skills.json.

Each repo is fetched at a pinned commit (no moving branches), then:
  * "skills"    -> copied into <dest>/<skill-name>/ (default: ./.claude/skills, project level)
  * "workspace" -> copied whole (minus heavy folders) into third_party/<id>/ for kits that expect their own root

Usage:
  python tools/install_skills.py list
  python tools/install_skills.py install [id ...]     # no ids = all
  python tools/install_skills.py install --user       # into ~/.claude/skills instead
Needs only git and Python 3.9+. Third-party skills can run commands on your machine: read each SKILL.md first.
"""
from __future__ import annotations

import argparse
import glob
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = Path(__file__).with_name("skills.json")


def load_manifest(path: Path = MANIFEST) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))["skills"]


def fetch(repo: str, commit: str, into: Path) -> None:
    """Shallow-fetch exactly one commit (works for any sha GitHub allows)."""
    def git(*args: str) -> None:
        r = subprocess.run(["git", *args], cwd=into, capture_output=True, text=True)
        if r.returncode:
            raise RuntimeError(f"git {' '.join(args)} failed: {r.stderr.strip() or r.stdout.strip()}")
    into.mkdir(parents=True, exist_ok=True)
    git("init", "-q")
    git("remote", "add", "origin", repo)
    git("fetch", "-q", "--depth", "1", "origin", commit)
    git("checkout", "-q", "FETCH_HEAD")


def _copy(src: Path, dst: Path, include: list[str] | None = None, exclude: list[str] | None = None) -> None:
    if dst.exists():
        shutil.rmtree(dst)
    skip = set(exclude or []) | {".git"}
    if include is None:
        shutil.copytree(src, dst, ignore=lambda _d, names: [n for n in names if n in skip])
        return
    dst.mkdir(parents=True)
    for name in include:
        p = src / name
        if not p.exists():
            raise RuntimeError(f"{name} not found in {src.name}")
        if p.is_dir():
            shutil.copytree(p, dst / name, ignore=lambda _d, names: [n for n in names if n in skip])
        else:
            shutil.copy2(p, dst / name)


def install_one(entry: dict, skills_dir: Path, third_party: Path, log=print) -> list[str]:
    done: list[str] = []
    with tempfile.TemporaryDirectory(prefix="vidcut-skill-") as tmp:
        work = Path(tmp) / "repo"
        fetch(entry["repo"], entry["commit"], work)
        for spec in entry.get("skills", []):
            if "*" in spec["src"]:
                sources = [(Path(p), Path(p).name) for p in sorted(glob.glob(str(work / spec["src"])))
                           if (Path(p) / "SKILL.md").is_file()]
            else:
                sources = [(work / spec["src"], spec["dest"])]
            for src, name in sources:
                if not (src / "SKILL.md").is_file():
                    raise RuntimeError(f"{entry['id']}: no SKILL.md in {spec['src']}")
                _copy(src, skills_dir / name, spec.get("include"))
                done.append(f"skill {name}")
        ws = entry.get("workspace")
        if ws is not None:
            _copy(work, third_party / entry["id"], exclude=ws.get("exclude"))
            done.append(f"workspace third_party/{entry['id']}")
    for d in done:
        log(f"  + {d}")
    return done


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["list", "install"])
    ap.add_argument("ids", nargs="*")
    ap.add_argument("--user", action="store_true", help="install skills into ~/.claude/skills (all projects)")
    ap.add_argument("--manifest", type=Path, default=MANIFEST)
    ap.add_argument("--dest", type=Path, help="override the skills folder")
    a = ap.parse_args(argv)

    entries = load_manifest(a.manifest)
    if a.command == "list":
        for e in entries:
            print(f"{e['id']:<24} {e['step']:<34} {e['license']:<11} {e['commit'][:7]}  {e['repo']}")
        return 0

    known = {e["id"] for e in entries}
    unknown = [i for i in a.ids if i not in known]
    if unknown:
        print(f"unknown id: {', '.join(unknown)} (see: list)", file=sys.stderr)
        return 2
    if shutil.which("git") is None:
        print("git not found. Install it (winget install Git.Git) and run again.", file=sys.stderr)
        return 2
    skills_dir = a.dest or (Path.home() / ".claude" / "skills" if a.user else ROOT / ".claude" / "skills")
    failed = 0
    for e in entries:
        if a.ids and e["id"] not in a.ids:
            continue
        print(f"[{e['id']}] {e['step']}")
        try:
            install_one(e, skills_dir, ROOT / "third_party")
        except Exception as exc:  # keep going so one bad repo doesn't block the rest
            failed += 1
            print(f"  ! {exc}", file=sys.stderr)
    print(f"\nskills folder: {skills_dir}")
    print("Restart Claude Code (open a new chat) so the new skills are loaded.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
