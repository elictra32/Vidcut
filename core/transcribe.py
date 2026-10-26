"""Speech-to-text with faster-whisper (CPU, int8). Times returned are relative to the audio
passed in (the selection output), not to any source file."""
import os

from core import media
from core.media import Cancelled, NoAudioError  # noqa: F401  (re-exported for callers)
from core.thai_split import Token

MODELS = ("large-v3", "medium", "small")


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


def _default_factory(name: str):
    from faster_whisper import WhisperModel
    # os.cpu_count() counts hardware threads; assume 2 per core so we match physical cores.
    return WhisperModel(name, device="cpu", compute_type="int8",
                        cpu_threads=max(1, (os.cpu_count() or 2) // 2))


def transcribe(wav_path: str, model_name: str = "large-v3", progress_cb=None, cancel_event=None,
               model_factory=None) -> list[Token]:
    model = (model_factory or _default_factory)(model_name)
    segments, info = model.transcribe(wav_path, language="th", word_timestamps=True, vad_filter=True)
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
