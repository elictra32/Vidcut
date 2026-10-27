"""Measure a finished short in numbers, optionally against style.json (the targets taken from the reference clips).

  python scripts/measure.py clip.mp4                  # prints the measurements as JSON
  python scripts/measure.py clip.mp4 --check          # also scores it against ../style.json (percent of checks passed)

Needs ffmpeg/ffprobe on PATH and numpy. Everything is measured from pixels and samples, nothing is guessed.
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
CARD_RGB = np.array([0x27, 0x11, 0x36])
SEAM_Y = 963
TITLE_BAND = (650, 1300)  # rows where the hook title lives


def run(*args):
    return subprocess.run(args, capture_output=True, text=True)


def probe(path):
    j = json.loads(run("ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", path).stdout)
    v = next(s for s in j["streams"] if s["codec_type"] == "video")
    a = next((s for s in j["streams"] if s["codec_type"] == "audio"), {})
    num, den = v["r_frame_rate"].split("/")
    return dict(width=v["width"], height=v["height"], fps=round(int(num) / int(den), 3), duration=round(float(j["format"]["duration"]), 2),
                video_codec=v["codec_name"], video_kbps=round(int(v.get("bit_rate", 0)) / 1000), audio_codec=a.get("codec_name"),
                audio_kbps=round(int(a.get("bit_rate", 0)) / 1000), sample_rate=int(a.get("sample_rate", 0)))


def frames(path, w, h, vf="", pix="rgb24"):
    p = subprocess.Popen(["ffmpeg", "-v", "error", "-i", path, "-vf", f"{vf + ',' if vf else ''}scale={w}:{h},format={pix}", "-f", "rawvideo", "-"],
                         stdout=subprocess.PIPE)
    ch = 3 if pix == "rgb24" else 1
    n = w * h * ch
    while True:
        b = p.stdout.read(n)
        if len(b) < n:
            break
        yield np.frombuffer(b, np.uint8).reshape(h, w, ch) if ch == 3 else np.frombuffer(b, np.uint8).reshape(h, w)


def shots_and_card(path, fps):
    small = np.array(list(frames(path, 108, 192))).astype(np.int16)
    d = np.abs(small[1:] - small[:-1]).mean(axis=(1, 2, 3))
    cuts = [0] + [int(i) + 1 for i in np.where(d > 40)[0]] + [len(small)]
    # split-screen seam, judged on the outer columns only (the title never reaches them)
    row = lambda r: np.abs(small[:, r, :, :] - small[:, r - 1, :, :])[:, list(range(0, 9)) + list(range(99, 108)), :].mean(axis=(1, 2))
    seam = row(96)
    around = (row(93) + row(99)) / 2
    split = seam > 3 * around + 4
    card = (np.abs(small - (CARD_RGB // 1)).max(axis=3) < 10).mean(axis=(1, 2)) > 0.95
    card_start = float(np.argmax(card) / fps) if card.any() else None
    shots = []
    for a, b in zip(cuts[:-1], cuts[1:]):
        shots.append(dict(t0=round(a / fps, 2), t1=round(b / fps, 2), dur=round((b - a) / fps, 2),
                          kind="end_card" if card[(a + b) // 2] else ("split" if split[a:b].mean() > 0.5 else "single")))
    # hard cut = a one-frame jump with calm frames on both sides; a dissolve/fade leaves a ramp next to the jump
    idx = [int(i) for i in np.where(d > 40)[0]]
    soft = sum(1 for i in idx if (i > 0 and d[i - 1] > 8) or (i + 1 < len(d) and d[i + 1] > 8))
    return shots, card_start, soft, small


def _band_frames(path, seconds):
    h = TITLE_BAND[1] - TITLE_BAND[0]
    p = subprocess.Popen(["ffmpeg", "-v", "error", "-t", str(seconds), "-i", path, "-vf", f"crop=1080:{h}:0:{TITLE_BAND[0]},format=rgb24",
                          "-f", "rawvideo", "-"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    n = 1080 * h * 3
    try:
        while True:
            b = p.stdout.read(n)
            if len(b) < n:
                return
            yield np.frombuffer(b, np.uint8).reshape(h, 1080, 3)
    finally:
        p.kill()


def title_window(path, fps, first_shot_s):
    """Title ink box (frame 10) and its fade, from per-pixel alpha against the same shot once the title is gone.
    alpha = (frame - clean background) / (white - clean background), median over pixels the title covers on a still background."""
    bg_i = int(min(first_shot_s - 0.3, 6.8) * fps)
    if bg_i < int(5.6 * fps):
        return None                       # the first shot ends before the title could be gone: no clean background to compare with
    want = {10, bg_i, bg_i - 12}
    keep = {}
    for i, f in enumerate(_band_frames(path, bg_i / fps + 0.2)):
        if i in want:
            keep[i] = f.copy()
        if i >= bg_i:
            break
    ref, bg, bg2 = keep.get(10), keep.get(bg_i), keep.get(bg_i - 12)
    if ref is None or bg is None or (ref.min(axis=2) >= 235).sum() < 20000:
        return None
    ink = ref.min(axis=2) >= 235
    rows, cols = np.where(ink.sum(axis=1) > 8)[0], np.where(ink.sum(axis=0) > 3)[0]
    ref32, bg32 = ref.astype(np.float32), bg.astype(np.float32)
    stable = (np.abs(bg32 - bg2.astype(np.float32)).max(axis=2) < 5) & (bg32.mean(axis=2) < 190)
    m = stable & ((ref32 - bg32).min(axis=2) > 40) & (ref.min(axis=2) > 200)
    if m.sum() < 5000:
        return None
    b = bg32[m]
    alpha = []
    for i, f in enumerate(_band_frames(path, bg_i / fps + 0.2)):
        alpha.append(float(np.median(((f[m].astype(np.float32) - b) / (255 - b)).mean(axis=1))))
        if i >= bg_i:
            break
    a = np.array(alpha)
    shown = np.where(a < 0.97)[0]
    gone = np.where(a < 0.06)[0]
    return dict(start_s=round(float(np.argmax(a > 0.5)) / fps, 2),
                full_until_s=round(float(shown[0]) / fps, 2) if len(shown) else None,
                gone_s=round(float(gone[0]) / fps, 2) if len(gone) else None,
                ink_x=[int(cols.min()), int(cols.max())], ink_width_px=int(cols.max() - cols.min() + 1),
                ink_y=[int(rows.min() + TITLE_BAND[0]), int(rows.max() + TITLE_BAND[0])],
                center=[round((cols.min() + cols.max()) / 2), round((rows.min() + rows.max()) / 2 + TITLE_BAND[0])])


def audio(path, end_card_start):
    out = run("ffmpeg", "-hide_banner", "-nostats", "-i", path, "-af", "ebur128=peak=true", "-f", "null", "-").stderr
    summ = out[out.rfind("Summary"):]
    grab = lambda pat: float(re.search(pat, summ).group(1))
    res = dict(lufs=grab(r"I:\s+(-?[\d.]+) LUFS"), lra=grab(r"LRA:\s+(-?[\d.]+) LU"), true_peak_dbfs=grab(r"Peak:\s+(-?[\d.]+) dBFS"))
    sil = run("ffmpeg", "-hide_banner", "-nostats", "-i", path, "-af", "silencedetect=n=-45dB:d=0.15", "-f", "null", "-").stderr
    starts = [float(x) for x in re.findall(r"silence_start: ([\d.]+)", sil)]
    durs = [float(x) for x in re.findall(r"silence_duration: ([\d.]+)", sil)]
    pauses = [(s, d) for s, d in zip(starts, durs) if end_card_start is None or s < end_card_start - 0.3]
    res["pauses_ge_0.3s"] = sum(1 for _, d in pauses if d >= 0.3)
    res["longest_pause_s"] = round(max([d for _, d in pauses], default=0), 2)
    if end_card_start is not None:
        t = run("ffmpeg", "-hide_banner", "-nostats", "-ss", str(end_card_start + 0.2), "-i", path, "-af", "volumedetect", "-f", "null", "-").stderr
        m = re.search(r"max_volume: (-?[\d.]+) dB", t)
        res["end_card_max_volume_db"] = float(m.group(1)) if m else None
    return res


def watermark(path, shots, fps):
    boxes = []
    for s in shots:
        if s["kind"] != "single" or s["dur"] < 1:
            continue
        t = (s["t0"] + s["t1"]) / 2
        r = subprocess.run(["ffmpeg", "-v", "error", "-ss", str(t), "-i", path, "-frames:v", "1", "-vf", "crop=280:130:800:60,format=rgb24",
                            "-f", "rawvideo", "-"], capture_output=True)
        a = np.frombuffer(r.stdout, np.uint8).reshape(130, 280, 3)
        m = a.min(axis=2) >= 235
        ys, xs = np.where(m)
        if len(xs) > 200:
            boxes.append((xs.min() + 800, xs.max() + 800, ys.min() + 60, ys.max() + 60))
    if not boxes:
        return None
    b = np.median(np.array(boxes), axis=0).astype(int)
    return dict(x=[int(b[0]), int(b[1])], y=[int(b[2]), int(b[3])], width_px=int(b[1] - b[0] + 1), right_margin_px=int(1079 - b[1]), top_margin_px=int(b[2]))


def measure(path):
    info = probe(path)
    fps = info["fps"]
    shots, card_start, soft, _ = shots_and_card(path, fps)
    body = [s for s in shots if s["kind"] != "end_card"]
    durs = [s["dur"] for s in body]
    cuts = len(shots) - 1
    return dict(file=str(path), **info,
                cuts_total=cuts, cuts_per_minute=round(cuts / info["duration"] * 60, 1),
                shot_mean_s=round(float(np.mean(durs)), 2), shot_median_s=round(float(np.median(durs)), 2),
                shortest_flash_s=min(durs), first_shot_kind=shots[0]["kind"], first_shot_s=shots[0]["dur"],
                soft_cuts=soft, shots=shots,
                end_card=None if card_start is None else dict(start_s=round(card_start, 2), duration_s=round(info["duration"] - card_start, 2)),
                title=title_window(path, fps, shots[0]["dur"]), watermark=watermark(path, shots, fps), audio=audio(path, card_start))


def check(m, style):
    """Each target: (value, lo, hi). Returns the list of results and the percent that passed."""
    def get(d, path):
        for k in path.split("."):
            if d is None:
                return None
            d = d.get(k) if isinstance(d, dict) else d[int(k)]
        return d
    rows = []
    for key, (lo, hi) in style["targets"].items():
        v = get(m, key)
        ok = v is not None and (lo is None or v >= lo) and (hi is None or v <= hi)
        rows.append(dict(check=key, value=v, want=[lo, hi], ok=bool(ok)))
    return rows, round(100 * sum(r["ok"] for r in rows) / len(rows), 1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("clip")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--style", default=str(HERE.parent / "style.json"))
    a = ap.parse_args()
    m = measure(a.clip)
    if a.check:
        rows, pct = check(m, json.loads(Path(a.style).read_text(encoding="utf-8")))
        for r in rows:
            print(("PASS " if r["ok"] else "FAIL ") + f"{r['check']:<28} {r['value']!s:<12} want {r['want']}")
        print(f"\nmatch: {pct}% ({sum(r['ok'] for r in rows)}/{len(rows)} checks)")
        return 0 if pct == 100 else 1
    print(json.dumps(m, ensure_ascii=False, indent=1, default=float))


if __name__ == "__main__":
    sys.exit(main())
