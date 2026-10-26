"""Canned Thai transcription used when VIDCUT_FAKE_WHISPER=1 (UI tests only, no model download)."""
from types import SimpleNamespace as NS

SENTENCES = [("สวัสดี", "ครับ", "ทุกคน"), ("วันนี้", "เรามา", "ตัดต่อ", "วิดีโอ", "กัน")]


def factory(name):
    class Model:
        def transcribe(self, audio, **kw):
            dur = len(audio) / 16000  # the real model also receives 16 kHz samples
            segs = []
            for (a, b), words in zip([(0.05, 0.35), (0.45, 0.9)], SENTENCES):
                t, step = a * dur, (b - a) * dur / len(words)
                ws = [NS(word=x, start=t + i * step, end=t + (i + 1) * step) for i, x in enumerate(words)]
                segs.append(NS(words=ws, start=ws[0].start, end=ws[-1].end))
            return iter(segs), NS(duration=dur)
    return Model()
