"""Thai subtitles in the house look: transcribe offline, chunk into short readable cues, style as ASS.

  python scripts/subtitles.py transcribe clip.mp4 -o clip.srt --model-dir DIR --vad silero_vad.onnx [--from 3.1]
      Whisper (sherpa-onnx, int8, runs on CPU, nothing leaves the machine). Needs: pip install sherpa-onnx pythainlp numpy
      DIR holds *-encoder*.onnx, *-decoder*.onnx, *-tokens.txt of a sherpa-onnx Whisper model (turbo: ~560 MB), release
      asset "sherpa-onnx-whisper-turbo.tar.bz2" and "silero_vad.onnx" on github.com/k2-fsa/sherpa-onnx (tag asr-models).
  build_short.py reads the .srt through  "subtitles": {"file": "clip.srt"}  in edl.json.

Timing is per speech segment (VAD), words inside a segment are spread by character count: good to about +-0.3 s, so READ AND FIX
THE .srt before publishing. Whisper makes Thai spelling mistakes, especially on trading jargon and mumbled speech.
"""
import argparse
import glob
import re
import sys
import wave
from pathlib import Path

import numpy as np

MAX_LINE_CHARS = 20        # Thai characters per line at the house subtitle size (1080 wide, ~930 px usable)
MAX_CUE_CHARS = 40         # two lines
CHARS_PER_SECOND = 13.0    # reading/speech pace used to spread a segment's text over its time
MIN_CUE_S = 0.7
FILLER = re.compile(r"^[\s.…,อ้าเอ่อออืมหือฮะค่ะครับนะ]*$")


def srt_time(t):
    ms = round(t * 1000)
    return "%02d:%02d:%02d,%03d" % (ms // 3600000, ms // 60000 % 60, ms // 1000 % 60, ms % 1000)


def parse_srt(text):
    cues = []
    for block in re.split(r"\n\s*\n", text.strip().replace("\r", "")):
        lines = block.split("\n")
        m = next((re.match(r"(\d+):(\d+):(\d+)[,.](\d+)\s*-->\s*(\d+):(\d+):(\d+)[,.](\d+)", l) for l in lines if "-->" in l), None)
        if not m:
            continue
        g = [int(x) for x in m.groups()]
        t0, t1 = g[0] * 3600 + g[1] * 60 + g[2] + g[3] / 1000, g[4] * 3600 + g[5] * 60 + g[6] + g[7] / 1000
        body = "\n".join(lines[lines.index(next(l for l in lines if "-->" in l)) + 1:]).strip()
        if body:
            cues.append((t0, t1, body))
    return cues


def write_srt(cues, path):
    Path(path).write_text("".join(f"{i}\n{srt_time(a)} --> {srt_time(b)}\n{t}\n\n" for i, (a, b, t) in enumerate(cues, 1)), encoding="utf-8")


def words(text):
    from pythainlp.tokenize import word_tokenize
    return [w for w in word_tokenize(text, engine="newmm", keep_whitespace=False) if w.strip()]


def wrap(text, max_line=MAX_LINE_CHARS):
    """Break Thai/Latin text at word boundaries into lines of at most max_line characters."""
    lines, cur = [], ""
    for w in words(text):
        sep = " " if cur and re.match(r"[A-Za-z0-9]", w[0]) and re.match(r"[A-Za-z0-9%.,]", cur[-1]) else ""
        if cur and len(cur) + len(sep) + len(w) > max_line:
            lines.append(cur)
            cur, sep = "", ""
        cur += sep + w
    if cur:
        lines.append(cur)
    # no orphan: if the last line is a lone short word, pull the previous line's last word down with it
    if len(lines) > 1 and len(lines[-1]) <= 4:
        prev = words(lines[-2])
        if len(prev) > 1:
            tail = prev[-1]
            lines[-2] = lines[-2][: len(lines[-2]) - len(tail)].rstrip()
            lines[-1] = tail + lines[-1]
    return lines


def chunk_segment(t0, t1, text):
    """One speech segment -> cues of up to two lines; time is spread by character count."""
    text = re.sub(r"\s+", " ", text).strip()
    if not text or FILLER.match(text):
        return []
    lines = wrap(text)
    groups = [lines[i:i + 2] for i in range(0, len(lines), 2)]
    total = sum(len("".join(g)) for g in groups) or 1
    cues, t = [], t0
    for g in groups:
        share = len("".join(g)) / total * (t1 - t0)
        cues.append((t, min(t1, t + max(share, 0.01)), "\n".join(g)))
        t += share
    return cues


def transcribe(clip, model_dir, vad_model, start=0.0, threads=4, language="th"):
    import subprocess
    import tempfile
    import sherpa_onnx
    m = Path(model_dir)
    pick = lambda pat: sorted(glob.glob(str(m / pat)))[0]
    rec = sherpa_onnx.OfflineRecognizer.from_whisper(
        encoder=next(iter(sorted(glob.glob(str(m / "*encoder*int8*.onnx")) + glob.glob(str(m / "*encoder*.onnx"))))),
        decoder=next(iter(sorted(glob.glob(str(m / "*decoder*int8*.onnx")) + glob.glob(str(m / "*decoder*.onnx"))))),
        tokens=pick("*tokens.txt"), language=language, num_threads=threads)
    with tempfile.TemporaryDirectory() as d:
        wav = Path(d) / "a.wav"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", str(start), "-i", str(clip), "-vn", "-ac", "1", "-ar", "16000", str(wav)], check=True)
        w = wave.open(str(wav))
        x = np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float32) / 32768
    vc = sherpa_onnx.VadModelConfig()
    vc.silero_vad.model = str(vad_model)
    vc.silero_vad.min_silence_duration = 0.3
    vc.silero_vad.max_speech_duration = 25
    vc.sample_rate = 16000
    vad = sherpa_onnx.VoiceActivityDetector(vc, buffer_size_in_seconds=60)
    win = vc.silero_vad.window_size
    for i in range(0, len(x), win):
        vad.accept_waveform(x[i:i + win])
    vad.flush()
    cues = []
    while not vad.empty():
        seg = vad.front
        t0, samples = seg.start / 16000, seg.samples
        vad.pop()
        s = rec.create_stream()
        s.accept_waveform(16000, samples)
        rec.decode_stream(s)
        cues += chunk_segment(start + t0, start + t0 + len(samples) / 16000, s.result.text)
    return cues


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["transcribe"])
    ap.add_argument("clip")
    ap.add_argument("-o", "--out", required=True)
    ap.add_argument("--model-dir", required=True)
    ap.add_argument("--vad", required=True)
    ap.add_argument("--from", dest="start", type=float, default=0.0, help="seconds of the clip to skip (times in the .srt stay on the clip's own timeline)")
    a = ap.parse_args()
    cues = transcribe(a.clip, a.model_dir, a.vad, a.start)
    write_srt(cues, a.out)
    print(f"{len(cues)} cues -> {a.out}")


if __name__ == "__main__":
    sys.exit(main())
