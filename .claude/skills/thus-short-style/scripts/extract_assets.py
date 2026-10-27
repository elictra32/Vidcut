"""Pull the brand end card and a transparent watermark out of a finished THUS short (run once).

  python extract_assets.py ref/ep3.mp4 --out ../assets

endcard.png  = one frame of the purple end card (exact, 1080x1920)
watermark.png = the THUS lock-up from that card, alpha taken from brightness against the card colour, scaled to the
                width it has on the video (WATERMARK_W). Only your own brand marks: run it on your own clips.
"""
import argparse
import subprocess
import sys
from pathlib import Path

import numpy as np

W, H = 1080, 1920
CARD_RGB = (0x27, 0x11, 0x36)
LOGO_BOX = (412, 969, 663, 1065)  # x0, y0, x1, y1 of the THUS lock-up on the end card (measured on 1080x1920)
WATERMARK_W = 207


def grab(path, t):
    r = subprocess.run(["ffmpeg", "-v", "error", "-ss", str(t), "-i", path, "-frames:v", "1", "-f", "rawvideo",
                        "-pix_fmt", "rgb24", "-"], capture_output=True, check=True)
    return np.frombuffer(r.stdout, np.uint8).reshape(H, W, 3)


def find_card_time(path, dur):
    t = dur - 0.5
    for _ in range(40):
        f = grab(path, t)
        if (np.abs(f.astype(int) - CARD_RGB).max(axis=2) < 8).mean() > 0.9:
            return t
        t -= 0.5
        if t < 0:
            break
    sys.exit("no purple end card found")


def main():
    from PIL import Image
    ap = argparse.ArgumentParser()
    ap.add_argument("clip")
    ap.add_argument("--out", default=str(Path(__file__).resolve().parent.parent / "assets"))
    a = ap.parse_args()
    dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", a.clip],
                               capture_output=True, text=True, check=True).stdout)
    f = grab(a.clip, find_card_time(a.clip, dur))
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    Image.fromarray(f).save(out / "endcard.png")
    x0, y0, x1, y1 = LOGO_BOX
    crop = f[y0:y1 + 1, x0:x1 + 1].astype(float)
    bg = np.array(CARD_RGB, float)
    alpha = np.clip(((crop - bg) / (255 - bg)).mean(axis=2), 0, 1)
    rgba = np.dstack([np.full(alpha.shape, 255), np.full(alpha.shape, 255), np.full(alpha.shape, 255), alpha * 255]).astype(np.uint8)
    im = Image.fromarray(rgba, "RGBA")
    im = im.resize((WATERMARK_W, round(im.height * WATERMARK_W / im.width)), Image.LANCZOS)
    im.save(out / "watermark.png")
    print("wrote", out / "endcard.png", out / "watermark.png", im.size)


if __name__ == "__main__":
    main()
