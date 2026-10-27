"""Build and run the ffmpeg export. One seeked input per selected piece (fast on hour-long
sources), concat, per-clip framing, then libass subtitles. ffmpeg runs with cwd set to a temp
work dir and references the ASS file, graph script and fonts by relative name, which avoids
Windows path escaping inside filter strings."""
import json
import os
import re
import shutil
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path

from core import media
from core.ass import RenderedSub, to_ass, to_srt
from core.encode import encoder_args, output_extension, source_video_kbps
from core.media import Cancelled, FFmpegError  # noqa: F401  (Cancelled re-exported for callers)
from core.models import Clip, ExportSettings, Overlay, Project, Selection
from core.presets import PRESETS, Preset
from core.timeline import Piece, edited_duration, enabled_keeps, selection_pieces, subtitles_for_export

FONTS_SRC = Path(__file__).resolve().parent.parent / "fonts"
FPS = 30
AUDIO_RATE = 48000
SAMPLES_PER_FRAME = AUDIO_RATE // FPS  # 1600: audio is cut to whole frames so video and audio stay locked
BATCH = 12  # pieces per ffmpeg pass: every piece is its own input/decoder (~45 MB each), and Windows caps argv at 32k
_name_lock = threading.Lock()


class ExportError(Exception):
    def __init__(self, code: str, message_th: str, details: str = ""):
        super().__init__(message_th)
        self.code, self.message_th, self.details = code, message_th, details


@dataclass
class ExportResult:
    video: str
    srt: str


def _fmt(x: float) -> str:
    return f"{x:.3f}".rstrip("0").rstrip(".") or "0"


def frame_counts(pieces: list[Piece]) -> list[int]:
    """Output frames for each piece. Boundaries are rounded cumulatively from the exact edited times,
    so rounding never accumulates over many cuts (subtitles use the exact times)."""
    if not pieces:
        return []
    last = pieces[-1]
    bounds = [round(p.out_start * FPS) for p in pieces] + [round((last.out_start + last.src_end - last.src_start) * FPS)]
    return [bounds[i + 1] - bounds[i] for i in range(len(pieces))]


def _frame_chain(clip: Clip, W: int, H: int, tag: str, n_frames: int) -> list[str]:
    """Statements turning input `tag` into a WxH stream [v{tag}] of exactly n_frames frames at FPS."""
    # setpts first: after an input seek the first frame is not at 0, which would shift fps's frame grid
    tail = (f"fps={FPS},tpad=stop=4:stop_mode=clone,trim=end_frame={n_frames},setpts=PTS-STARTPTS,"
            f"setsar=1,format=yuv420p")
    src = f"[r{tag}]"
    head = [f"[{tag}:v]setpts=PTS-STARTPTS[r{tag}]"]
    if abs(clip.width / clip.height - W / H) < 0.01:
        return head + [f"{src}scale={W}:{H},{tail}[v{tag}]"]
    if clip.framing.mode == "crop":
        cx = _fmt(min(1.0, max(0.0, clip.framing.crop_center_x)))
        return head + [f"{src}scale={W}:{H}:force_original_aspect_ratio=increase,"
                       f"crop={W}:{H}:'(iw-ow)*{cx}':'(ih-oh)/2',{tail}[v{tag}]"]
    return head + [f"{src}split[bg{tag}][fg{tag}]",
                   f"[bg{tag}]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},boxblur=20:5[bb{tag}]",
                   f"[fg{tag}]scale={W}:{H}:force_original_aspect_ratio=decrease[ff{tag}]",
                   f"[bb{tag}][ff{tag}]overlay=(W-w)/2:(H-h)/2,{tail}[v{tag}]"]


def overlay_statements(overlays: list[Overlay], first_input: int, src: str, W: int, H: int,
                       timed: bool = True) -> tuple[list[str], str]:
    """Filter statements laying each image (ffmpeg input first_input + k) over the video labelled `src`.
    Returns the statements and the label of the result."""
    stmts, cur = [], src
    for k, o in enumerate(overlays):
        i = first_input + k
        px = max(2, round(o.width * W))
        stmts.append(f"[{i}:v]scale={px}:-1,format=rgba,colorchannelmixer=aa={_fmt(min(1.0, max(0.0, o.opacity)))}[ov{k}]")
        gate = ""
        if timed and (o.start is not None or o.end is not None):
            a = _fmt(o.start if o.start is not None else 0.0)
            b = _fmt(o.end) if o.end is not None else "1e9"
            gate = f":enable='between(t,{a},{b})'"
        nxt = f"ovo{k}"
        stmts.append(f"[{cur}][ov{k}]overlay=x={round(o.x * W)}-w/2:y={round(o.y * H)}-h/2:shortest=1{gate}[{nxt}]")
        cur = nxt
    return stmts, cur


def build_filter_graph(clips: list[Clip], pieces: list[Piece], preset: Preset, ass_name: str | None,
                       include_audio: bool = True, frames: list[int] | None = None,
                       overlays: list[Overlay] | None = None, timed_overlays: bool = True) -> str:
    """Per-piece frame-exact video/audio, concatenated; subtitles burned in when `ass_name` is given.
    Outputs are always [vout] and (with audio) [ac]."""
    by_id = {c.id: c for c in clips}
    frames = frames if frames is not None else frame_counts(pieces)
    stmts, concat_in = [], ""
    for i, (p, n) in enumerate(zip(pieces, frames)):
        clip = by_id[p.clip_id]
        stmts += _frame_chain(clip, preset.width, preset.height, str(i), n)
        concat_in += f"[v{i}]"
        if include_audio:
            samples = n * SAMPLES_PER_FRAME
            if clip.has_audio:
                stmts.append(f"[{i}:a]aresample={AUDIO_RATE},aformat=channel_layouts=stereo,asetpts=PTS-STARTPTS,"
                             f"apad=pad_dur=0.15,atrim=end_sample={samples},asetpts=PTS-STARTPTS[a{i}]")
            else:
                stmts.append(f"anullsrc=r={AUDIO_RATE}:cl=stereo,atrim=end_sample={samples},asetpts=PTS-STARTPTS[a{i}]")
            concat_in += f"[a{i}]"
    a_flag, a_out = (1, "[ac]") if include_audio else (0, "")
    ov, label = overlay_statements(overlays or [], len(pieces), "vc", preset.width, preset.height, timed_overlays)
    if ass_name:
        stmts.append(f"{concat_in}concat=n={len(pieces)}:v=1:a={a_flag}[vc]{a_out}")
        stmts += ov
        stmts.append(f"[{label}]{ASS_FILTER.format(name=ass_name)}[vout]")
    elif ov:
        stmts.append(f"{concat_in}concat=n={len(pieces)}:v=1:a={a_flag}[vc]{a_out}")
        stmts += ov
        stmts.append(f"[{label}]null[vout]")
    else:
        stmts.append(f"{concat_in}concat=n={len(pieces)}:v=1:a={a_flag}[vout]{a_out}")
    return ";\n".join(stmts)


def build_ffmpeg_cmd(clips: list[Clip], pieces: list[Piece], preset: Preset, ass_name: str | None,
                     out_name: str, include_audio: bool = True, frame_only: bool = False,
                     frames: list[int] | None = None, intermediate: bool = False,
                     encoder: list[str] | None = None, overlays: list[Overlay] | None = None,
                     timed_overlays: bool = True) -> list[str]:
    """ffmpeg argv (without the binary). One seeked input per piece; the graph is passed inline
    (`-filter_complex_script` is deprecated in FFmpeg 7+)."""
    by_id = {c.id: c for c in clips}
    cmd: list[str] = []
    for p in pieces:
        cmd += ["-ss", _fmt(p.src_start), "-t", _fmt(p.src_end - p.src_start), "-i", by_id[p.clip_id].path]
    length = _fmt(sum(p.src_end - p.src_start for p in pieces) + 1.0)
    for o in overlays or []:
        cmd += ["-loop", "1", "-t", length, "-i", o.path]
    cmd += ["-filter_complex", build_filter_graph(clips, pieces, preset, ass_name, include_audio, frames,
                                                 overlays, timed_overlays),
            "-map", "[vout]"]
    if include_audio:
        cmd += ["-map", "[ac]"]
    if frame_only:
        return cmd + ["-frames:v", "1", out_name]
    if intermediate:  # near-lossless scratch part, joined and encoded for real in the final pass
        return cmd + ["-c:v", "libx264", "-preset", "ultrafast", "-crf", "14", "-pix_fmt", "yuv420p",
                      "-c:a", "pcm_s16le", out_name]
    if encoder is None:  # default format and quality, sized for these pieces
        encoder = encoder_args(ExportSettings(), preset.name, sum(p.src_end - p.src_start for p in pieces))
    return cmd + encoder + [out_name]


def _extra_pieces(clips: list[Clip], role: str, start_at: float, only_ids: list[str] | None = None) -> list[Piece]:
    """The enabled keeps of every clip with `role`, in clip order, laid out from `start_at`."""
    out, t = [], start_at
    for c in clips:
        if c.role != role or (only_ids is not None and c.id not in only_ids):
            continue
        for k in enabled_keeps(c):
            out.append(Piece(c.id, k.start, k.end, t))
            t += k.end - k.start
    return out


def export_pieces(project: Project, selection: Selection, intro_ids: list[str] | None = None) -> tuple[list[Piece], float]:
    """Everything that goes into the file, in order: intro clips, the selection of the main timeline,
    outro clips. Returns the pieces (out_start along the whole output) and the intro's length."""
    main = selection_pieces(project.clips, selection)  # ValueError("selection_invalid") when unusable
    intro = _extra_pieces(project.clips, "intro", 0.0, intro_ids)
    intro_dur = sum(p.src_end - p.src_start for p in intro)
    main = [Piece(p.clip_id, p.src_start, p.src_end, p.out_start + intro_dur) for p in main]
    main_end = intro_dur + sum(p.src_end - p.src_start for p in main)
    return intro + main + _extra_pieces(project.clips, "outro", main_end), intro_dur


def export_duration(project: Project) -> float:
    """Length in seconds of the file an export would produce (raises ValueError when the selection is unusable)."""
    selection = project.selection or Selection(0.0, edited_duration(project.clips))
    return sum(p.src_end - p.src_start for p in export_pieces(project, selection)[0])


def _prepare(project: Project, selection: Selection, with_extras: bool = True, intro_ids: list[str] | None = None):
    preset = PRESETS[project.preset]
    try:
        if with_extras:
            pieces, intro_dur = export_pieces(project, selection, intro_ids)
        else:
            pieces, intro_dur = selection_pieces(project.clips, selection), 0.0
    except ValueError:
        raise ExportError("selection_invalid",
                          "The selection is invalid, or no enabled sections are left. "
                          "Please set start/end again and re-enable at least one cut section") from None
    rendered = [RenderedSub(a + intro_dur, b + intro_dur, s.text, s.x, s.y, s.scale, project.style.reveal)
                for a, b, s in subtitles_for_export(project.clips, project.subtitles, selection)]
    return preset, pieces, rendered


# `ass` instead of `subtitles`: only `ass` can ask libass for complex (OpenType) shaping. With the default shaper Thai
# tone marks above an upper vowel (ที่ นี้ ...) land inside the vowel and disappear.
ASS_FILTER = "ass={name}:fontsdir=fonts:shaping=complex"

MANIFEST_SUFFIX = ".vidcut.json"


def manifest_path(video_path: str) -> str:
    return os.path.splitext(video_path)[0] + MANIFEST_SUFFIX


def write_cut_manifest(video_path: str, clips: list[Clip], pieces: list[Piece]) -> None:
    """A small file next to the exported video saying which parts of which source went where. It lets captions made
    for the ORIGINAL video be mapped onto this cut version later (see /api/clips/{id}/cut-manifest)."""
    by_id = {c.id: c for c in clips}
    sources: dict[str, dict] = {}
    for p in pieces:
        c = by_id[p.clip_id]
        src = sources.setdefault(c.id, {"name": os.path.basename(c.path), "path": c.path, "role": c.role,
                                        "duration": c.duration, "pieces": []})
        src["pieces"].append({"src_start": p.src_start, "src_end": p.src_end, "out_start": p.out_start})
    Path(manifest_path(video_path)).write_text(json.dumps({"version": 1, "video": os.path.basename(video_path),
                                                           "sources": list(sources.values())}, ensure_ascii=False, indent=1),
                                               encoding="utf-8")


def _workdir(preset: Preset, project: Project, rendered) -> str:
    wd = tempfile.mkdtemp(prefix="vidcut_")
    Path(wd, "subs.ass").write_text(to_ass(rendered, project.style, (preset.width, preset.height)),
                                    encoding="utf-8")
    shutil.copytree(FONTS_SRC, Path(wd, "fonts"))
    return wd


def _safe_stem(path: str) -> str:
    return re.sub(r'[<>:"/\\|?*\s]+', "_", Path(path).stem).strip("_") or "clip"


def _plan(pieces: list[Piece]) -> tuple[list[Piece], list[int]]:
    """Pieces with their output frame counts; pieces shorter than a frame are dropped."""
    frames = frame_counts(pieces)
    kept = [(p, n) for p, n in zip(pieces, frames) if n > 0]
    return [p for p, _ in kept], [n for _, n in kept]


def _ffmpeg(cmd, duration, progress_cb, cancel_event, wd):
    try:
        media.run_ffmpeg(cmd, duration, progress_cb, cancel_event, cwd=wd)
    except FFmpegError as e:
        raise ExportError("export_failed",
                          "Export failed. Try a shorter selection, or check that the original file still exists", e.details) from e
    except FileNotFoundError as e:
        if "ffmpeg" in str(e).lower():
            raise ExportError("ffmpeg_missing", "ffmpeg not found. Please run setup.bat again") from e
        raise


def _unique_paths(out_dir: str, stem: str, ext: str) -> tuple[str, str]:
    """First free <stem>[_N].<ext>/.srt pair: an export never replaces an earlier one."""
    n = 1
    while True:
        name = stem if n == 1 else f"{stem}_{n}"
        video, srt = os.path.join(out_dir, f"{name}.{ext}"), os.path.join(out_dir, name + ".srt")
        if not os.path.exists(video) and not os.path.exists(srt):
            return video, srt
        n += 1


def run_export(project: Project, out_dir: str, progress_cb=None, cancel_event=None, *, selection: Selection | None = None,
               intro_ids: list[str] | None = None, name_suffix: str = "", max_video_kbps: int | None = None) -> ExportResult:
    """`selection`/`intro_ids`/`name_suffix`/`max_video_kbps` let the episode splitter render one episode:
    its own range, its own intro clip, its own file name and a bitrate cap that keeps it under the size limit."""
    if not project.clips:
        raise ExportError("no_clips", "No clips in the project. Please add a clip first")
    selection = selection or project.selection or Selection(0.0, edited_duration(project.clips))
    preset, pieces, rendered = _prepare(project, selection, intro_ids=intro_ids)
    pieces, frames = _plan(pieces)
    if not pieces:
        raise ExportError("selection_invalid", "The selection is too short. Please choose a longer range")
    for o in project.overlays:
        if not os.path.isfile(o.path):
            raise ExportError("overlay_missing", f"Overlay image not found: {o.path}")
    report = progress_cb or (lambda p, m="": None)
    total = sum(p.src_end - p.src_start for p in pieces)
    ext = output_extension(project.export)
    encoder = encoder_args(project.export, preset.name, total, source_video_kbps(project.clips), max_video_kbps)
    out_name = f"out.{ext}"
    wd = _workdir(preset, project, rendered)
    try:
        if len(pieces) <= BATCH:
            cmd = build_ffmpeg_cmd(project.clips, pieces, preset, "subs.ass", out_name, frames=frames, encoder=encoder,
                                   overlays=project.overlays)
            _ffmpeg(cmd, total, progress_cb, cancel_event, wd)
        else:
            # Bounded passes: each batch is rendered to a scratch part, then one pass joins the parts
            # and burns the subtitles. Keeps memory and the command line small however many cuts there are.
            spans = [(i, min(i + BATCH, len(pieces))) for i in range(0, len(pieces), BATCH)]
            done = 0.0
            for k, (i, j) in enumerate(spans):
                part = pieces[i:j]
                length = sum(p.src_end - p.src_start for p in part)
                cmd = build_ffmpeg_cmd(project.clips, part, preset, None, f"part_{k}.mkv", frames=frames[i:j],
                                       intermediate=True)
                base = done
                _ffmpeg(cmd, length, lambda f, m="", base=base, length=length: report(0.8 * (base + f * length) / total, m),
                        cancel_event, wd)
                done += length
            Path(wd, "parts.txt").write_text("".join(f"file 'part_{k}.mkv'\n" for k in range(len(spans))),
                                             encoding="utf-8")
            final = ["-f", "concat", "-safe", "0", "-i", "parts.txt"]
            for o in project.overlays:
                final += ["-loop", "1", "-t", _fmt(total + 1.0), "-i", o.path]
            ov, label = overlay_statements(project.overlays, 1, "vc", preset.width, preset.height)
            graph = ";".join(["[0:v]null[vc]", *ov, f"[{label}]{ASS_FILTER.format(name='subs.ass')}[vout]"])
            final += ["-filter_complex", graph, "-map", "[vout]", "-map", "0:a?", *encoder, out_name]
            _ffmpeg(final, total, lambda f, m="": report(0.8 + 0.2 * f, m), cancel_event, wd)
        os.makedirs(out_dir, exist_ok=True)
        with _name_lock:
            video, srt = _unique_paths(out_dir, f"{_safe_stem(project.clips[0].path)}_{preset.name}{name_suffix}", ext)
            shutil.move(os.path.join(wd, out_name), video)
            Path(srt).write_text(to_srt(rendered), encoding="utf-8")
            write_cut_manifest(video, project.clips, pieces)
        return ExportResult(video, srt)
    finally:
        shutil.rmtree(wd, ignore_errors=True)


def render_preview_frame(project: Project, edited_t: float, out_png: str) -> None:
    """Render one real frame (with subtitles and framing) at the given edited time."""
    total = edited_duration(project.clips)
    t = min(max(0.0, edited_t), max(0.0, total - 0.1))
    preset, pieces, rendered = _prepare(project, Selection(t, min(total, t + 0.1)), with_extras=False)
    pieces, frames = _plan(pieces)
    wd = _workdir(preset, project, rendered)
    try:
        cmd = build_ffmpeg_cmd(project.clips, pieces, preset, "subs.ass", "frame.png",
                               include_audio=False, frame_only=True, frames=frames,
                               overlays=[o for o in project.overlays if os.path.isfile(o.path)], timed_overlays=False)
        try:
            media.run_ffmpeg(cmd, cwd=wd)
        except FFmpegError as e:
            raise ExportError("preview_failed", "Couldn't create the sample frame", e.details) from e
        os.makedirs(os.path.dirname(os.path.abspath(out_png)), exist_ok=True)
        shutil.move(os.path.join(wd, "frame.png"), out_png)
    finally:
        shutil.rmtree(wd, ignore_errors=True)
