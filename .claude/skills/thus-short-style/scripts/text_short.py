"""Render a text-only vertical short (1080x1920, 25 fps) from a scene list, using the house title rules:
every line scaled to ~835 px ink width, stacked and centred, white Prompt Medium, hard cuts, no fades, locked frame.

  python scripts/text_short.py scenes.json -o out.mp4
  scenes.json: {"background": "#14161F", "scenes": [{"lines": ["..", ".."], "seconds": 3.5, "media": "broll/01.mp4"}, ...]}
  "media" (optional, path relative to scenes.json) = a video/gif/image used as the scene background, darkened so the text stays readable.

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
        out = str(Path(a.out).resolve())
        base = Path(a.scenes).resolve().parent
        if any(sc.get("media") for sc in spec["scenes"]):
            names = []
            for i, sc in enumerate(spec["scenes"]):
                n = bs.frame_count(sc["seconds"])
                part = f"bg{i:03d}.mov"
                m = sc.get("media")
                if m:
                    f = Path(m) if Path(m).is_absolute() else base / m
                    if not f.is_file():
                        sys.exit(f"media not found: {f}")
                    pre = ["-loop", "1", "-framerate", str(bs.FPS)] if f.suffix.lower() in bs.IMAGE_EXT else ["-stream_loop", "-1"]
                    src = [*pre, "-t", f"{n / bs.FPS + 0.5:.3f}", "-i", str(f)]
                    vf = bs.cover() + f",drawbox=x=0:y=0:w={bs.W}:h={bs.H}:color=black@{spec.get('darken', 0.5)}:t=fill,format=yuv420p"
                else:
                    src = ["-f", "lavfi", "-i", f"color=c=0x{bg}:s={bs.W}x{bs.H}:r={bs.FPS}"]
                    vf = "format=yuv420p"
                bs.run(["ffmpeg", "-v", "error", "-y", *src, "-vf", vf, "-frames:v", str(n), "-r", str(bs.FPS), "-an", "-c:v", "libx264", "-crf", "12",
                        "-preset", "veryfast", "-pix_fmt", "yuv420p", part], cwd=work)
                names.append(part)
            (work / "bg.txt").write_text("".join(f"file '{n}'\n" for n in names), encoding="utf-8")
            bs.run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", "bg.txt", "-f", "lavfi", "-i", f"anullsrc=r=48000:cl=stereo:d={dur:.4f}",
                    "-vf", "ass=scenes.ass:fontsdir=fonts:shaping=complex,format=yuv420p", "-frames:v", str(frames), "-c:v", "libx264", "-preset", "medium", "-crf", "18",
                    "-c:a", "aac", "-b:a", "240k", "-shortest", "-movflags", "+faststart", out], cwd=work)
        else:
            bs.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"color=c=0x{bg}:s={bs.W}x{bs.H}:r={bs.FPS}:d={dur:.4f}",
                    "-f", "lavfi", "-i", f"anullsrc=r=48000:cl=stereo:d={dur:.4f}", "-vf", "ass=scenes.ass:fontsdir=fonts:shaping=complex,format=yuv420p",
                    "-frames:v", str(frames), "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-c:a", "aac", "-b:a", "240k", "-shortest",
                    "-movflags", "+faststart", out], cwd=work)
        print(json.dumps(dict(output=str(Path(a.out).resolve()), seconds=round(dur, 2), scenes=len(spec["scenes"]), frames=frames)))
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    main()
