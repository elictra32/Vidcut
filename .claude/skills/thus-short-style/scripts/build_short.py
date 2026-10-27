"""Render a THUS-style short (1080x1920, 25 fps) from an edit list.

  python scripts/build_short.py edl.json -o out.mp4        # see ../examples/edl.example.json

Inputs are two synced camera files (top = the guest/woman side, bottom = the host/man side, as in the reference clips).
Each shot is a stacked split-screen of both cameras, a close-up of one, or a full-frame B-roll file (video, gif or image; the main audio keeps playing). The hook title is laid out
automatically (every line scaled so its ink is ~835 px wide, stacked, centred at 534,938), then the transparent
watermark is laid over the video part, the purple end card is appended, and loudness is set to -16 LUFS.
All numbers come from ../style.json / ../style-guide.md. Needs ffmpeg with libass, Python 3.9+, numpy.
"""
import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
SKILL = HERE.parent
W, H, FPS = 1080, 1920, 25
SEAM = 960                      # the reference seam sits at y=963; half the frame is the clean number to build with
TITLE_INK_W = 835               # px, measured 835-838 on both reference clips
TITLE_CENTER = (534, 938)       # x, y of the title block (measured 532-538, 935-940)
TITLE_GAP = 40                  # px between the ink boxes of two lines (measured 19-77)
TITLE_MAX_INK_H = 240           # a line that would get taller than this takes its neighbour's size (ep4: 'จิตใจ')
TITLE_SECONDS, TITLE_FADE = 5.04, 1.0   # full opacity until 4.04 s, then a linear 1.0 s fade (alpha measured per frame on both clips)
WATERMARK_XY = (818, 91)
END_CARD_SECONDS = 3.1
LUFS = -16.0
FONT_FAMILY, FONT_FILE = "Prompt Medium", "Prompt-Medium.ttf"   # closest shipped weight to the title's (see style-guide.md)
OUTLINE = 1.5                   # same-colour outline thickens Medium towards the reference's ink density (0.353)


def run(cmd, cwd=None, check=True, capture=True):
    r = subprocess.run(cmd, cwd=cwd, capture_output=capture)
    if check and r.returncode:
        sys.exit(f"command failed: {' '.join(map(str, cmd))}\n{r.stderr.decode(errors='replace')[-2000:] if capture else ''}")
    return r


def probe_size(path):
    out = run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height", "-of", "csv=p=0", str(path)]).stdout
    w, h = out.decode().strip().split(",")
    return int(w), int(h)


def frame_count(seconds):
    return max(1, round(seconds * FPS))


# ---------------------------------------------------------------- title layout (closed loop through libass)
class Title:
    def __init__(self, work, fonts_dir):
        self.work = Path(work)
        (self.work / "fonts").mkdir(exist_ok=True)
        src = Path(fonts_dir) / FONT_FILE
        if not src.exists():
            sys.exit(f"font not found: {src} (pass --fonts DIR, it must contain {FONT_FILE})")
        shutil.copy(src, self.work / "fonts" / FONT_FILE)

    @staticmethod
    def _ass(events, seconds):
        head = ("[Script Info]\nScriptType: v4.00+\nPlayResX: %d\nPlayResY: %d\nWrapStyle: 2\nScaledBorderAndShadow: yes\n\n"
                "[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, "
                "Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
                "Style: T,%s,100,&H00FFFFFF,&H00FFFFFF,&H00FFFFFF,&H00000000,0,0,0,0,100,100,0,0,1,%s,0,5,0,0,0,1\n\n"
                "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n") % (W, H, FONT_FAMILY, OUTLINE)
        end = "0:00:%05.2f" % seconds
        return head + "".join("Dialogue: 0,0:00:00.00,%s,T,,0,0,0,,{%s}%s\n" % (end, tags, text) for text, tags in events)

    def ink(self, ass_text, name="cal.ass"):
        (self.work / name).write_text(ass_text, encoding="utf-8")
        r = run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", f"color=black:s={W}x{H}:r={FPS}:d=0.2,format=gray", "-vf",
                 f"ass={name}:fontsdir=fonts:shaping=complex", "-frames:v", "1", "-f", "rawvideo", "-"], cwd=self.work)
        return np.frombuffer(r.stdout, np.uint8).reshape(H, W)

    @staticmethod
    def bbox(img, y0=0, y1=H):
        m = img[y0:y1] > 128
        ys, xs = np.where(m)
        if not len(xs):
            return None
        return xs.min(), xs.max(), ys.min() + y0, ys.max() + y0

    def measure(self, text):
        """Ink box of `text` at fs=100 placed with \\an5\\pos(540,960): (width, height, centre offset x, centre offset y)."""
        img = self.ink(self._ass([(text, r"\an5\pos(540,960)\fs100")], 0.2))
        b = self.bbox(img)
        if b is None:
            sys.exit(f"title line renders nothing: {text!r} (font {FONT_FAMILY} missing from libass?)")
        x0, x1, y0, y1 = b
        return dict(w=x1 - x0 + 1, h=y1 - y0 + 1, dx=(x0 + x1) / 2 - 540, dy=(y0 + y1) / 2 - 960)

    def place(self, lines):
        """Fit and stack `lines` (see the TITLE_* constants). Returns ([(text, ass tags)], planned ink y ranges, font sizes)."""
        m = [self.measure(t) for t in lines]
        fs = [100 * TITLE_INK_W / x["w"] for x in m]
        for i, x in enumerate(m):                      # lines that would get too tall take a neighbour's size
            if x["h"] * fs[i] / 100 > TITLE_MAX_INK_H:
                fs[i] = None
        for i in range(len(fs)):
            if fs[i] is None:
                rest = [f for f in fs[i + 1:] if f] or [f for f in fs[:i] if f]
                fs[i] = rest[0] if rest else 100 * TITLE_MAX_INK_H / m[i]["h"]
        hs = [m[i]["h"] * fs[i] / 100 for i in range(len(m))]
        top = TITLE_CENTER[1] - (sum(hs) + TITLE_GAP * (len(m) - 1)) / 2
        events, targets = [], []
        for i, t in enumerate(lines):
            cy = top + hs[i] / 2
            x = TITLE_CENTER[0] - m[i]["dx"] * fs[i] / 100
            y = cy - m[i]["dy"] * fs[i] / 100
            events.append((t, r"\an5\pos(%.1f,%.1f)\fs%.1f" % (x, y, fs[i])))
            targets.append((top, top + hs[i]))
            top += hs[i] + TITLE_GAP
        return events, targets, fs

    def layout(self, lines, seconds=TITLE_SECONDS, fade=TITLE_FADE):
        events, targets, fs = self.place(lines)
        if fade:
            events = [(t, tag + r"\fad(0,%d)" % round(fade * 1000)) for t, tag in events]
        (self.work / "title.ass").write_text(self._ass(events, seconds), encoding="utf-8")
        return dict(font_sizes=[round(f, 1) for f in fs], planned_ink_y=[(round(a), round(b)) for a, b in targets])


# ---------------------------------------------------------------- shots
def crop_expr(cam_w, cam_h, aspect, zoom, cx):
    """Crop window of the given aspect (w/h) using zoom (1 = full camera height) centred at fraction cx of the camera width."""
    ch = cam_h / zoom
    cw = ch * aspect
    if cw > cam_w:
        cw = cam_w
        ch = cw / aspect
    x = min(max(cx * cam_w - cw / 2, 0), cam_w - cw)
    y = (cam_h - ch) / 2
    return f"crop={cw:.2f}:{ch:.2f}:{x:.2f}:{y:.2f}"


IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}


def cover(w=W, h=H):
    """Fill the frame (crop the overflow), same pixel format and rate as every other shot."""
    return f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},fps={FPS},setsar=1"


def render_shot(i, shot, edl, sizes, work):
    cams = edl["cams"]
    t0, t1 = shot["t0"], shot["t1"]
    n = frame_count(t1 - t0)
    dur = n / FPS
    out = work / f"part{i:03d}.mov"
    ins, graph, count = [], [], [0]

    def add(src, pre=(), seek=None):
        ins.extend([*pre, *(["-ss", f"{seek:.3f}"] if seek is not None else []), "-t", f"{dur + 0.5:.3f}", "-i", str(src)])
        count[0] += 1
        return count[0] - 1

    if shot["layout"] == "split":
        top, bot = cams["top"], cams["bottom"]
        a, b = add(top, seek=t0), add(bot, seek=t0)
        s = shot.get("zoom", edl.get("split_zoom", 1.0))
        graph = [f"[{a}:v]{crop_expr(*sizes['top'], W / (H / 2), shot.get('zoom_top', s), shot.get('cx_top', 0.5))},scale={W}:{H // 2},setsar=1[t]",
                 f"[{b}:v]{crop_expr(*sizes['bottom'], W / (H / 2), shot.get('zoom_bottom', s), shot.get('cx_bottom', 0.5))},scale={W}:{H // 2},setsar=1[b]",
                 "[t][b]vstack=inputs=2[v]"]
    elif shot["layout"] == "broll":
        f = Path(shot["file"])
        still = f.suffix.lower() in IMAGE_EXT
        a = add(f, pre=["-loop", "1", "-framerate", str(FPS)] if still else ["-stream_loop", "-1"], seek=None if still else shot.get("from", 0.0))
        graph = [f"[{a}:v]{cover()}[v]"]
    else:
        key = shot["cam"]
        a = add(cams[key], seek=t0)
        graph = [f"[{a}:v]{crop_expr(*sizes[key], W / H, shot.get('zoom', edl.get('cu_zoom', 1.0)), shot.get('cx', 0.5))},scale={W}:{H},setsar=1[v]"]
    aud = edl.get("audio", "bottom")
    ai = add(cams.get(aud, aud), seek=t0)
    graph.append(f"[{ai}:a]aresample=48000,apad=whole_dur={dur:.4f},atrim=0:{dur:.4f},aformat=channel_layouts=stereo[a]")
    cmd = ["ffmpeg", "-v", "error", "-y", *ins, "-filter_complex", ";".join(graph), "-map", "[v]", "-map", "[a]", "-r", str(FPS),
           "-frames:v", str(n), "-c:v", "libx264", "-crf", "12", "-preset", "veryfast", "-pix_fmt", "yuv420p", "-c:a", "pcm_s16le", "-ar", "48000", str(out)]
    run(cmd)
    return out, n


def render_end_card(edl, work):
    n = frame_count(edl.get("end_card_seconds", END_CARD_SECONDS))
    png = Path(edl.get("end_card_png") or SKILL / "assets" / "endcard.png")
    out = work / "part_end.mov"
    run(["ffmpeg", "-v", "error", "-y", "-loop", "1", "-framerate", str(FPS), "-i", str(png), "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
         "-frames:v", str(n), "-t", f"{n / FPS:.4f}", "-vf", f"scale={W}:{H},setsar=1,format=yuv420p", "-c:v", "libx264", "-crf", "12", "-preset", "veryfast",
         "-c:a", "pcm_s16le", "-ar", "48000", str(out)])
    return out, n


def measure_loudness(path):
    r = run(["ffmpeg", "-v", "info", "-nostats", "-i", str(path), "-vn", "-af", f"loudnorm=I={LUFS}:TP=-1.5:LRA=7:print_format=json", "-f", "null", "-"])
    txt = r.stderr.decode()
    return json.loads(txt[txt.rfind("{"):txt.rfind("}") + 1])


def build(edl, out_path, fonts_dir, keep=False):
    work = Path(tempfile.mkdtemp(prefix="thus-short-"))
    try:
        sizes = {k: probe_size(v) for k, v in edl["cams"].items()}
        parts, video_frames = [], 0
        for i, shot in enumerate(edl["shots"]):
            p, n = render_shot(i, shot, edl, sizes, work)
            parts.append(p)
            video_frames += n
            print(f"  shot {i}: {shot['layout']:<5} {shot['t0']}-{shot['t1']}  ({n} frames)")
        endp, _ = render_end_card(edl, work)
        parts.append(endp)
        (work / "list.txt").write_text("".join(f"file '{p.name}'\n" for p in parts), encoding="utf-8")
        run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", "list.txt", "-c", "copy", "joined.mov"], cwd=work)
        info = {}
        title = edl.get("title")
        graph = "[0:v]null[v0]"
        if title:
            T = Title(work, fonts_dir)
            info["title"] = T.layout(title["lines"], title.get("seconds", TITLE_SECONDS), title.get("fade", TITLE_FADE))
            graph = "[v0]ass=title.ass:fontsdir=fonts:shaping=complex[vt]"
        wm = Path(edl.get("watermark_png") or SKILL / "assets" / "watermark.png")
        tv = video_frames / FPS
        chain = (f"[0:v][1:v]overlay={WATERMARK_XY[0]}:{WATERMARK_XY[1]}:enable='lt(t,{tv:.4f})':format=auto[v0];"
                 + (graph if title else "[v0]null[vt]"))
        loud = measure_loudness(work / "joined.mov")
        af = (f"loudnorm=I={LUFS}:TP=-1.5:LRA=7:measured_I={loud['input_i']}:measured_TP={loud['input_tp']}:measured_LRA={loud['input_lra']}:"
              f"measured_thresh={loud['input_thresh']}:offset={loud['target_offset']}:linear=true,aresample=48000")
        shutil.copy(wm, work / "wm.png")
        out = Path(out_path).resolve()
        run(["ffmpeg", "-v", "error", "-y", "-i", "joined.mov", "-framerate", str(FPS), "-loop", "1", "-i", "wm.png", "-filter_complex", chain,
             "-af", af, "-map", "[vt]", "-map", "0:a", "-shortest", "-r", str(FPS), "-c:v", "libx264", "-preset", "medium", "-b:v", "2400k",
             "-maxrate", "2800k", "-bufsize", "5600k", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "240k", "-ar", "48000", "-ac", "2",
             "-movflags", "+faststart", str(out)], cwd=work)
        info.update(video_s=round(tv, 2), end_card_s=round(edl.get("end_card_seconds", END_CARD_SECONDS), 2), output=str(out))
        return info
    finally:
        if not keep:
            shutil.rmtree(work, ignore_errors=True)
        else:
            print("work dir kept:", work)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("edl")
    ap.add_argument("-o", "--out", required=True)
    ap.add_argument("--fonts", default=None, help=f"folder containing {FONT_FILE} (default: the repo's fonts/ next to .claude/)")
    ap.add_argument("--keep", action="store_true")
    a = ap.parse_args()
    edl = json.loads(Path(a.edl).read_text(encoding="utf-8"))
    base = Path(a.edl).resolve().parent
    edl["cams"] = {k: str((base / v) if not Path(v).is_absolute() else v) for k, v in edl["cams"].items()}
    for need in ("top", "bottom"):
        if need not in edl["cams"]:
            sys.exit(f"edl.cams needs '{need}'")
    for s in edl["shots"]:
        if s["layout"] not in ("split", "cu", "broll") or (s["layout"] == "cu" and s.get("cam") not in edl["cams"]):
            sys.exit(f"bad shot: {s}")
        if s["layout"] == "broll":
            f = Path(s.get("file", ""))
            s["file"] = str(f if f.is_absolute() else base / f)
            if not Path(s["file"]).is_file():
                sys.exit(f"b-roll file not found: {s['file']}")
        if s["t1"] <= s["t0"]:
            sys.exit(f"shot ends before it starts: {s}")
    fonts = a.fonts or next((str(p / "fonts") for p in SKILL.parents if (p / "fonts" / FONT_FILE).exists()), None)
    if edl.get("title") and not fonts:
        sys.exit("fonts folder not found, pass --fonts")
    info = build(edl, a.out, fonts, a.keep)
    print(json.dumps(info, ensure_ascii=False))


if __name__ == "__main__":
    main()
