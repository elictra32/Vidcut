"""Turn a Media Finder cue-sheet.md into B-roll shots / text-short scenes.

  python scripts/cue_to_edl.py out/cue-sheet.md --folder out --as shots  > broll_shots.json
  python scripts/cue_to_edl.py out/cue-sheet.md --folder out --as scenes > scenes.json

Reads the "Beat map" table: | # | 00:03-00:06 | beat / line | visual idea | `01_a.mp4` 🎬 · `01_b.gif` ... |
Picks, per beat, the first file by preference (video, gif, image; --prefer to change; --skip-gif for paid ads: Tenor GIFs are organic-only).
`shots`  -> {"shots": [{"layout": "broll", "file", "t0", "t1"}]}  merge into an edl.json (times are in the voice-over / camera timeline)
`scenes` -> {"scenes": [{"lines", "seconds", "media"}]}           for text_short.py (the beat text is split on spaces into up to 3 lines)
"""
import argparse
import json
import re
import sys
from pathlib import Path

KIND = {".mp4": "video", ".mov": "video", ".webm": "video", ".gif": "gif", ".png": "image", ".jpg": "image", ".jpeg": "image", ".webp": "image"}


def seconds(ts):
    m = re.fullmatch(r"(?:(\d+):)?(\d+):(\d+(?:\.\d+)?)", ts.strip())
    if not m:
        raise ValueError(f"bad timestamp {ts!r}")
    h, mi, s = m.groups()
    return int(h or 0) * 3600 + int(mi) * 60 + float(s)


def parse(text):
    beats = []
    for line in text.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 5 or not cells[0].isdigit():
            continue
        m = re.fullmatch(r"(\S+?)\s*[–—-]\s*(\S+)", cells[1])
        if not m:
            continue
        beats.append(dict(n=int(cells[0]), t0=seconds(m.group(1)), t1=seconds(m.group(2)), text=re.sub(r"^HOOK\s*[—-]\s*", "", cells[2]).strip(' "“”'),
                          files=re.findall(r"`([^`]+)`", cells[4])))
    return beats


def pick(files, prefer, skip_gif):
    order = [k for k in prefer if not (skip_gif and k == "gif")]
    ranked = sorted((f for f in files if KIND.get(Path(f).suffix.lower()) in order), key=lambda f: order.index(KIND[Path(f).suffix.lower()]))
    return ranked[0] if ranked else None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cue_sheet")
    ap.add_argument("--folder", default=None, help="folder holding the files (default: next to the cue sheet)")
    ap.add_argument("--as", dest="mode", choices=["shots", "scenes"], default="shots")
    ap.add_argument("--prefer", default="video,gif,image")
    ap.add_argument("--skip-gif", action="store_true")
    a = ap.parse_args()
    cue = Path(a.cue_sheet)
    folder = Path(a.folder) if a.folder else cue.parent
    beats = parse(cue.read_text(encoding="utf-8"))
    if not beats:
        sys.exit("no beat rows found in the cue sheet")
    out, missing = [], []
    for b in beats:
        f = pick(b["files"], a.prefer.split(","), a.skip_gif)
        if f is None or not (folder / f).is_file():
            missing.append(b["n"])
            continue
        if a.mode == "shots":
            out.append({"layout": "broll", "file": str((folder / f).resolve()), "t0": round(b["t0"], 2), "t1": round(b["t1"], 2)})
        else:
            words = b["text"].split()
            k = min(3, max(1, len(words)))
            lines = [" ".join(words[i * len(words) // k:(i + 1) * len(words) // k]) for i in range(k)] or [b["text"]]
            out.append({"lines": [x for x in lines if x], "seconds": round(b["t1"] - b["t0"], 2), "media": str((folder / f).resolve())})
    if missing:
        print(f"beats without a usable file: {missing}", file=sys.stderr)
    print(json.dumps({a.mode: out}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
