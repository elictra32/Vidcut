"""Selection -> audio -> Whisper tokens -> Thai words -> subtitle lines anchored to source time."""
import os
import shutil
import tempfile
import uuid

from core.models import Selection, Subtitle
from core.presets import PRESETS
from core.thai_split import build_lines, tokens_to_words
from core.timeline import Piece, selection_pieces, selection_time_to_source
from core.transcribe import extract_selection_audio, transcribe

MIN_SUB_LEN = 0.05


def _end_to_source(pieces: list[Piece], clip_id: str, t: float) -> float:
    """Source time for a selection-relative END time, kept inside `clip_id`'s pieces."""
    mine = [p for p in pieces if p.clip_id == clip_id and p.out_start < t]
    p = mine[-1] if mine else next(p for p in pieces if p.clip_id == clip_id)
    return p.src_start + min(max(0.0, t - p.out_start), p.src_end - p.src_start)


def generate_subtitles(clips, selection: Selection, preset_name: str, model_name: str = "large-v3",
                       progress_cb=None, cancel_event=None, model_factory=None) -> list[Subtitle]:
    preset = PRESETS[preset_name]
    pieces = selection_pieces(clips, selection)
    wd = tempfile.mkdtemp(prefix="vidcut_asr_")
    try:
        wav = os.path.join(wd, "sel.wav")
        extract_selection_audio(clips, pieces, wav)
        tokens = transcribe(wav, model_name, progress_cb, cancel_event, model_factory)
    finally:
        shutil.rmtree(wd, ignore_errors=True)
    words = tokens_to_words(tokens)
    groups: list[tuple[str, list]] = []  # consecutive words belonging to the same clip
    for w in words:
        cid, _ = selection_time_to_source(pieces, w.start)
        if groups and groups[-1][0] == cid:
            groups[-1][1].append(w)
        else:
            groups.append((cid, [w]))
    subs: list[Subtitle] = []
    for cid, ws in groups:
        for line in build_lines(ws, preset.line_width, preset.max_lines):
            _, s = selection_time_to_source(pieces, line.start)
            e = max(_end_to_source(pieces, cid, line.end), s + MIN_SUB_LEN)
            subs.append(Subtitle(uuid.uuid4().hex, cid, s, e, line.text))
    return subs
