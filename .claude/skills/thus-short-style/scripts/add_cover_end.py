"""Put a cover image at the start and the THUS end card at the end of a finished short. Nothing else changes
(subtitles already burned into the clip stay; no title, no extra logo). Loudness is set to -16 LUFS.

  python add_cover_end.py "Short/clip.mp4" --cover "Short/vertical_covers_v2.png" -o "Short/clip_final.mp4"
  python add_cover_end.py clip.mp4 -o clip_final.mp4                 # end card only
  options: --cover-seconds 3.1   --no-loudness-fix is not offered: the house level is -16 LUFS

The cover is shown full-frame (cropped to 9:16 if needed) in silence; the clip then starts at 0 and the audio is not shifted.
"""
import argparse
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_short as bs  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("clip")
    ap.add_argument("-o", "--out", required=True)
    ap.add_argument("--cover", default=None)
    ap.add_argument("--cover-seconds", type=float, default=3.1)
    a = ap.parse_args()
    clip = Path(a.clip).resolve()
    if not clip.is_file():
        sys.exit(f"clip not found: {clip}")
    shots = []
    if a.cover:
        cover = Path(a.cover).resolve()
        if not cover.is_file():
            sys.exit(f"cover not found: {cover}")
        shots.append({"layout": "broll", "file": str(cover), "t0": 0, "t1": a.cover_seconds, "silent": True})
    shots.append({"layout": "broll", "file": str(clip), "t0": 0, "t1": "end"})
    edl = {"cams": {"top": str(clip), "bottom": str(clip)}, "audio": "bottom", "watermark": False, "shots": shots}
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "edl.json"
        p.write_text(json.dumps(edl), encoding="utf-8")
        sys.argv = ["build_short.py", str(p), "-o", str(Path(a.out).resolve())]
        bs.main()


if __name__ == "__main__":
    main()
