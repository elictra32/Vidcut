import threading
import wave
from types import SimpleNamespace as NS

import numpy as np
import pytest

from core.autosub import generate_subtitles
from core.media import Cancelled, NoAudioError
from core.models import Clip, Keep, Selection
from core.transcribe import transcribe
from tests.helpers import make_clip


def seg(*words):
    ws = [NS(word=w, start=s, end=e) for w, s, e in words]
    return NS(words=ws, start=ws[0].start, end=ws[-1].end, text="".join(w for w, _, _ in words))


def write_wav(path, seconds=1.0, rate=16000):
    """A 16 kHz mono 16-bit wav, as extract_selection_audio makes: a quiet 440 Hz tone."""
    t = np.arange(int(seconds * rate)) / rate
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes((np.sin(2 * np.pi * 440 * t) * 8000).astype(np.int16).tobytes())
    return str(path)


class FakeModel:
    def __init__(self, segments, duration=10.0):
        self.segments, self.duration, self.kwargs, self.audio = segments, duration, None, None

    def transcribe(self, audio, **kw):
        self.audio, self.kwargs = audio, kw
        return iter(self.segments), NS(duration=self.duration)


def factory_for(model):
    calls = []

    def factory(name):
        calls.append(name)
        return model
    factory.calls = calls
    return factory


def clip(cid, path, keeps, audio=True, duration=10):
    return Clip(id=cid, path=path, duration=duration, width=640, height=360, fps=25,
                has_audio=audio, keeps=[Keep(*k) for k in keeps])


@pytest.fixture
def clip1(tmp_path):
    p = make_clip(str(tmp_path / "a.mp4"), [("tone", 10)])
    return clip("c1", p, [(0, 4), (6, 10)])


def test_generate_subtitles_maps_to_source_time_across_a_cut(clip1):
    model = FakeModel([seg(("สวัสดี", 0.2, 0.8), ("ครับ", 0.8, 1.2), ("วันนี้", 2.5, 3.0))])
    subs = generate_subtitles([clip1], Selection(2, 6), "youtube", model_factory=factory_for(model))
    assert [s.text for s in subs] == ["สวัสดีครับ", "วันนี้"]
    assert subs[0].clip_id == "c1"
    assert (subs[0].src_start, subs[0].src_end) == pytest.approx((2.2, 3.2))
    assert (subs[1].src_start, subs[1].src_end) == pytest.approx((6.5, 7.0))
    assert all(len(s.id) == 32 for s in subs)


def test_generate_subtitles_never_spans_two_clips(tmp_path):
    a = clip("c1", make_clip(str(tmp_path / "a.mp4"), [("tone", 5)]), [(0, 5)], duration=5)
    b = clip("c2", make_clip(str(tmp_path / "b.mp4"), [("tone", 5)]), [(0, 5)], duration=5)
    model = FakeModel([seg(("ก่อน", 1.0, 1.9), ("แล้ว", 2.1, 2.6))])
    subs = generate_subtitles([a, b], Selection(3, 7), "youtube", model_factory=factory_for(model))
    assert [s.clip_id for s in subs] == ["c1", "c2"]
    assert subs[0].src_end <= 5.0 + 1e-6 and subs[1].src_start >= 0.0


def test_generate_subtitles_no_speech_returns_empty_list(clip1):
    subs = generate_subtitles([clip1], Selection(0, 4), "tiktok", model_factory=factory_for(FakeModel([])))
    assert subs == []


def test_generate_subtitles_no_audio_clip_raises_NoAudioError(tmp_path):
    p = make_clip(str(tmp_path / "n.mp4"), [("tone", 4)], with_audio=False)
    c = clip("c1", p, [(0, 4)], audio=False, duration=4)
    with pytest.raises(NoAudioError):
        generate_subtitles([c], Selection(0, 4), "tiktok", model_factory=factory_for(FakeModel([])))


def test_generate_subtitles_uses_preset_line_width(clip1):
    model = FakeModel([seg(*[(f"คำที่{i}", i * 0.2, i * 0.2 + 0.18) for i in range(20)])])
    tiktok = generate_subtitles([clip1], Selection(0, 4), "tiktok", model_factory=factory_for(model))
    youtube = generate_subtitles([clip1], Selection(0, 4), "youtube", model_factory=factory_for(model))
    assert len(tiktok) > len(youtube) >= 1


def test_transcribe_passes_th_word_timestamps_vad(tmp_path):
    model = FakeModel([seg(("สวัสดี", 0, 1))])
    f = factory_for(model)
    toks = transcribe(write_wav(tmp_path / "x.wav"), model_name="small", model_factory=f)
    assert f.calls == ["small"]
    assert model.kwargs["language"] == "th"
    assert model.kwargs["word_timestamps"] is True
    assert model.kwargs["vad_filter"] is True
    assert [(t.text, t.start, t.end) for t in toks] == [("สวัสดี", 0, 1)]


def test_transcribe_hands_whisper_decoded_audio_not_a_path(tmp_path):
    """faster-whisper opens a *path* with PyAV (av.open(..., metadata_errors=...)), which raises TypeError on
    the PyAV versions pip resolves on some Windows installs. We already have a plain wav: pass the samples."""
    model = FakeModel([seg(("สวัสดี", 0, 1))])
    transcribe(write_wav(tmp_path / "x.wav", seconds=2.0), model_factory=factory_for(model))
    assert isinstance(model.audio, np.ndarray) and model.audio.dtype == np.float32
    assert len(model.audio) == 32000 and np.abs(model.audio).max() <= 1.0 and np.abs(model.audio).max() > 0.1


def test_transcribe_of_a_wav_that_is_not_16k_mono_is_a_clear_error(tmp_path):
    bad = write_wav(tmp_path / "x.wav", rate=8000)
    with pytest.raises(ValueError, match="16 kHz"):
        transcribe(bad, model_factory=factory_for(FakeModel([])))


def test_transcribe_cancel(tmp_path):
    model = FakeModel([seg(("ก", 0, 1)), seg(("ข", 1, 2))])
    ev = threading.Event()
    ev.set()
    with pytest.raises(Cancelled):
        transcribe(write_wav(tmp_path / "x.wav"), model_factory=factory_for(model), cancel_event=ev)


def test_transcribe_reports_progress(tmp_path):
    model = FakeModel([seg(("ก", 0, 5)), seg(("ข", 5, 10))], duration=10.0)
    got = []
    transcribe(write_wav(tmp_path / "x.wav"), model_factory=factory_for(model),
               progress_cb=lambda p, m: got.append(p))
    assert got[-1] == pytest.approx(1.0) and got == sorted(got)


@pytest.mark.slow
def test_real_tiny_model_runs_on_synthetic_clip(tmp_path):
    p = make_clip(str(tmp_path / "t.mp4"), [("tone", 3)])
    c = clip("c1", p, [(0, 3)], duration=3)
    assert isinstance(generate_subtitles([c], Selection(0, 3), "tiktok", model_name="tiny"), list)


# ---- model download: progress and cancel (spec section 5.4), downloader injected --------------------
from core.transcribe import ensure_model  # noqa: E402

FW_PATTERNS = ["config.json", "preprocessor_config.json", "model.bin", "tokenizer.json", "vocabulary.*"]


def test_ensure_model_uses_the_cache_without_downloading():
    calls = []

    def dl(**kw):
        calls.append(kw)
        return "/cache/small"

    assert ensure_model("small", snapshot_download=dl) == "/cache/small"
    assert len(calls) == 1 and calls[0]["local_files_only"] is True
    assert calls[0]["repo_id"] == "Systran/faster-whisper-small" and calls[0]["allow_patterns"] == FW_PATTERNS


def test_ensure_model_downloads_and_reports_progress():
    def dl(**kw):
        if kw.get("local_files_only"):
            raise RuntimeError("not cached")
        files = kw["tqdm_class"](total=1000, unit="B")
        for _ in range(4):
            files.update(250)
        return "/cache/large"

    seen = []
    assert ensure_model("large-v3", progress_cb=lambda p, m="": seen.append((p, m)), snapshot_download=dl) == "/cache/large"
    fractions = [p for p, _ in seen]
    assert fractions == sorted(fractions) and fractions[-1] == pytest.approx(1.0)
    assert all("ดาวน์โหลด" in m for _, m in seen)


def test_ensure_model_only_counts_byte_bars():
    def dl(**kw):
        if kw.get("local_files_only"):
            raise RuntimeError("not cached")
        kw["tqdm_class"](total=5, unit="it").update(5)  # the "fetching N files" bar
        return "/cache/m"

    seen = []
    ensure_model("medium", progress_cb=lambda p, m="": seen.append(p), snapshot_download=dl)
    assert seen == []


def test_ensure_model_cancel_stops_the_download():
    def dl(**kw):
        if kw.get("local_files_only"):
            raise RuntimeError("not cached")
        kw["tqdm_class"](total=100, unit="B").update(10)
        raise AssertionError("download should have been cancelled")

    ev = threading.Event()
    ev.set()
    with pytest.raises(Cancelled):
        ensure_model("small", cancel_event=ev, snapshot_download=dl)


def test_model_dir_env_override(monkeypatch):
    monkeypatch.setenv("VIDCUT_MODEL_DIR", "D:\\models")
    got = {}

    def dl(**kw):
        got.update(kw)
        return "x"

    ensure_model("small", snapshot_download=dl)
    assert got["cache_dir"] == "D:\\models"
