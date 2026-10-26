"""Speech-to-text with faster-whisper (CPU, int8). Times returned are relative to the audio
passed in (the selection output), not to any source file."""
import os
import wave

import numpy as np

from core import media
from core.media import Cancelled, NoAudioError  # noqa: F401  (re-exported for callers)
from core.thai_split import Token

MODELS = ("large-v3", "medium", "small")
HF_REPOS = {n: f"Systran/faster-whisper-{n}" for n in MODELS}
# the same files faster-whisper itself fetches, so the cache we fill is the one it loads
HF_PATTERNS = ["config.json", "preprocessor_config.json", "model.bin", "tokenizer.json", "vocabulary.*"]


def model_cache_dir() -> str | None:
    """VIDCUT_MODEL_DIR relocates the model cache (e.g. when the Windows profile path has Thai characters)."""
    return os.environ.get("VIDCUT_MODEL_DIR") or None


def ensure_model(name: str, progress_cb=None, cancel_event=None, snapshot_download=None) -> str:
    """Local path of a Whisper model, downloading it first if needed, with progress and cancel."""
    if snapshot_download is None:
        from huggingface_hub import snapshot_download
    kw = {"repo_id": HF_REPOS.get(name, name), "allow_patterns": HF_PATTERNS, "cache_dir": model_cache_dir()}
    try:
        return snapshot_download(local_files_only=True, **kw)  # already downloaded: instant
    except Exception:  # noqa: BLE001 - "not cached" has several exception types across hub versions
        pass
    from tqdm.auto import tqdm

    bars: dict[int, list[float]] = {}
    last = [0.0]
    sink = open(os.devnull, "w")

    class Bar(tqdm):
        def __init__(self, *a, **k):
            k["disable"], k["file"] = False, sink  # a disabled tqdm never counts; keep the console quiet
            super().__init__(*a, **k)

        def update(self, n=1):
            out = super().update(n)
            if cancel_event is not None and cancel_event.is_set():
                raise Cancelled()
            if self.unit == "B" and self.total and progress_cb:
                bars[id(self)] = [self.n, self.total]
                done, total = sum(b[0] for b in bars.values()), sum(b[1] for b in bars.values())
                last[0] = max(last[0], min(1.0, done / total))  # more files may join: never go backwards
                progress_cb(last[0], f"กำลังดาวน์โหลดโมเดล {round(last[0] * 100)}% (ครั้งแรกครั้งเดียว)")
            return out

    try:
        return snapshot_download(tqdm_class=Bar, **kw)
    finally:
        sink.close()


def extract_selection_audio(clips, pieces, out_wav: str) -> None:
    """16 kHz mono wav of the selected pieces, concatenated. Clips without audio contribute
    silence; if no piece has audio at all, raises NoAudioError."""
    by_id = {c.id: c for c in clips}
    if not any(by_id[p.clip_id].has_audio for p in pieces):
        raise NoAudioError("no audio in selection")
    cmd, chains, labels = [], [], ""
    for i, p in enumerate(pieces):
        d = p.src_end - p.src_start
        c = by_id[p.clip_id]
        if c.has_audio:
            cmd += ["-ss", f"{p.src_start:.3f}", "-t", f"{d:.3f}", "-i", c.path]
            chains.append(f"[{i}:a]aresample=16000,aformat=channel_layouts=mono[a{i}]")
        else:
            cmd += ["-f", "lavfi", "-t", f"{d:.3f}", "-i", "anullsrc=r=16000:cl=mono"]
            chains.append(f"[{i}:a]anull[a{i}]")
        labels += f"[a{i}]"
    graph = ";".join(chains + [f"{labels}concat=n={len(pieces)}:v=0:a=1[out]"])
    media.run_ffmpeg(cmd + ["-filter_complex", graph, "-map", "[out]", "-ar", "16000", "-ac", "1", out_wav])


def load_audio(wav_path: str) -> np.ndarray:
    """Samples of a 16 kHz mono 16-bit wav (what extract_selection_audio writes) as float32 in [-1, 1].

    Whisper is given these samples, not the path: faster-whisper opens a path with PyAV using an option
    that older PyAV versions reject (TypeError: open() got an unexpected keyword argument 'metadata_errors')."""
    with wave.open(wav_path, "rb") as w:
        if (w.getframerate(), w.getnchannels(), w.getsampwidth()) != (16000, 1, 2):
            raise ValueError(f"expected a 16 kHz mono 16-bit wav, got {w.getframerate()} Hz, "
                             f"{w.getnchannels()} channel(s), {8 * w.getsampwidth()}-bit")
        raw = w.readframes(w.getnframes())
    return np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0


def _default_factory(name: str, progress_cb=None, cancel_event=None):
    from faster_whisper import WhisperModel
    path = ensure_model(name, progress_cb, cancel_event)
    if progress_cb:
        progress_cb(0.0, "กำลังโหลดโมเดลเข้าหน่วยความจำ")
    # os.cpu_count() counts hardware threads; assume 2 per core so we match physical cores.
    return WhisperModel(path, device="cpu", compute_type="int8",
                        cpu_threads=max(1, (os.cpu_count() or 2) // 2))


def transcribe(wav_path: str, model_name: str = "large-v3", progress_cb=None, cancel_event=None,
               model_factory=None) -> list[Token]:
    audio = load_audio(wav_path)
    model = model_factory(model_name) if model_factory else _default_factory(model_name, progress_cb, cancel_event)
    if cancel_event is not None and cancel_event.is_set():
        raise Cancelled()
    segments, info = model.transcribe(audio, language="th", word_timestamps=True, vad_filter=True)
    total = float(getattr(info, "duration", 0) or 0)
    tokens: list[Token] = []
    for s in segments:
        if cancel_event is not None and cancel_event.is_set():
            raise Cancelled()
        for w in s.words or []:
            tokens.append(Token(w.word, float(w.start), float(w.end)))
        if progress_cb and total > 0:
            progress_cb(min(1.0, float(s.end) / total), "")
    if cancel_event is not None and cancel_event.is_set():
        raise Cancelled()
    return tokens
