import threading
from types import SimpleNamespace as NS

import pytest

from core.autosub import generate_subtitles
from core.media import Cancelled, NoAudioError
from core.models import Clip, Keep, Selection
from core.transcribe import transcribe
from tests.helpers import make_clip


def seg(*words):
    ws = [NS(word=w, start=s, end=e) for w, s, e in words]
    return NS(words=ws, start=ws[0].start, end=ws[-1].end, text="".join(w for w, _, _ in words))


class FakeModel:
    def __init__(self, segments, duration=10.0):
        self.segments, self.duration, self.kwargs = segments, duration, None

    def transcribe(self, audio, **kw):
        self.kwargs = kw
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
    toks = transcribe(str(tmp_path / "x.wav"), model_name="small", model_factory=f)
    assert f.calls == ["small"]
    assert model.kwargs["language"] == "th"
    assert model.kwargs["word_timestamps"] is True
    assert model.kwargs["vad_filter"] is True
    assert [(t.text, t.start, t.end) for t in toks] == [("สวัสดี", 0, 1)]


def test_transcribe_cancel(tmp_path):
    model = FakeModel([seg(("ก", 0, 1)), seg(("ข", 1, 2))])
    ev = threading.Event()
    ev.set()
    with pytest.raises(Cancelled):
        transcribe(str(tmp_path / "x.wav"), model_factory=factory_for(model), cancel_event=ev)


def test_transcribe_reports_progress(tmp_path):
    model = FakeModel([seg(("ก", 0, 5)), seg(("ข", 5, 10))], duration=10.0)
    got = []
    transcribe(str(tmp_path / "x.wav"), model_factory=factory_for(model),
               progress_cb=lambda p, m: got.append(p))
    assert got[-1] == pytest.approx(1.0) and got == sorted(got)


@pytest.mark.slow
def test_real_tiny_model_runs_on_synthetic_clip(tmp_path):
    p = make_clip(str(tmp_path / "t.mp4"), [("tone", 3)])
    c = clip("c1", p, [(0, 3)], duration=3)
    assert isinstance(generate_subtitles([c], Selection(0, 3), "tiktok", model_name="tiny"), list)
