"""Render a text-only vertical short (1080x1920, 25 fps) from a scene list, using the house title rules:
every line scaled to ~835 px ink width, stacked and centred, white Prompt Medium, hard cuts, no fades, locked frame.

  python scripts/text_short.py scenes.json -o out.mp4
  scenes.json: {"background": "#14161F", "scenes": [{"lines": ["..", ".."], "seconds": 3.5}, ...]}

The output has a silent audio track (no voice is generated). Scene lengths are a reading pace, not tied to any recording.
"""
import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_short as bs  # noqa: E402


def stamp(t):
    cs = round(t * 100)
    return "%d:%02d:%02d.%02d" % (cs // 360000, cs // 6000 % 60, cs // 100 % 60, cs % 100)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("scenes")
    ap.add_argument("-o", "--out", required=True)
    ap.add_argument("--fonts", default=None)
    a = ap.parse_args()
    spec = json.loads(Path(a.scenes).read_text(encoding="utf-8"))
    fonts = a.fonts or next((str(p / "fonts") for p in bs.SKILL.parents if (p / "fonts" / bs.FONT_FILE).exists()), None)
    if not fonts:
        sys.exit("fonts folder not found, pass --fonts")
    work = Path(tempfile.mkdtemp(prefix="thus-text-"))
    try:
        T = bs.Title(work, fonts)
        body, t, frames = [], 0, 0
        for sc in spec["scenes"]:
            n = bs.frame_count(sc["seconds"])
            events, _, _ = T.place(sc["lines"])
            for text, tag in events:
                body.append("Dialogue: 0,%s,%s,T,,0,0,0,,{%s}%s\n" % (stamp(frames / bs.FPS), stamp((frames + n) / bs.FPS), tag, text))
            frames += n
        (work / "scenes.ass").write_text(T._ass([], 0) + "".join(body), encoding="utf-8")
        bg = spec.get("background", "#14161F").lstrip("#")
        dur = frames / bs.FPS
        bs.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"color=c=0x{bg}:s={bs.W}x{bs.H}:r={bs.FPS}:d={dur:.4f}",
                "-f", "lavfi", "-i", f"anullsrc=r=48000:cl=stereo:d={dur:.4f}", "-vf", "ass=scenes.ass:fontsdir=fonts:shaping=complex,format=yuv420p",
                "-frames:v", str(frames), "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-c:a", "aac", "-b:a", "240k", "-shortest",
                "-movflags", "+faststart", str(Path(a.out).resolve())], cwd=work)
        print(json.dumps(dict(output=str(Path(a.out).resolve()), seconds=round(dur, 2), scenes=len(spec["scenes"]), frames=frames)))
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    main()
