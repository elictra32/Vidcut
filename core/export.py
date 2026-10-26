"""Build and run the ffmpeg export. One seeked input per selected piece (fast on hour-long
sources), concat, per-clip framing, then libass subtitles. ffmpeg runs with cwd set to a temp
work dir and references the ASS file, graph script and fonts by relative name, which avoids
Windows path escaping inside filter strings."""
import os
import re
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from core import media
from core.ass import RenderedSub, to_ass, to_srt
from core.media import Cancelled, FFmpegError  # noqa: F401  (Cancelled re-exported for callers)
from core.models import Clip, Project, Selection
from core.presets import PRESETS, Preset
from core.timeline import Piece, edited_duration, selection_pieces, subtitles_for_export

GRAPH_NAME = "graph.txt"
FONTS_SRC = Path(__file__).resolve().parent.parent / "fonts"
FPS = 30


class ExportError(Exception):
    def __init__(self, code: str, message_th: str, details: str = ""):
        super().__init__(message_th)
        self.code, self.message_th, self.details = code, message_th, details


@dataclass
class ExportResult:
    mp4: str
    srt: str


def _fmt(x: float) -> str:
    return f"{x:.3f}".rstrip("0").rstrip(".") or "0"


def _frame_chain(clip: Clip, W: int, H: int, tag: str) -> list[str]:
    """Filter statements turning the raw input [in{tag}] into a WxH stream [v{tag}]."""
    src = f"[{tag}:v]"
    tail = f"fps={FPS},setsar=1,format=yuv420p"
    if abs(clip.width / clip.height - W / H) < 0.01:
        return [f"{src}scale={W}:{H},{tail}[v{tag}]"]
    if clip.framing.mode == "crop":
        cx = _fmt(min(1.0, max(0.0, clip.framing.crop_center_x)))
        return [f"{src}scale={W}:{H}:force_original_aspect_ratio=increase,"
                f"crop={W}:{H}:'(iw-ow)*{cx}':'(ih-oh)/2',{tail}[v{tag}]"]
    return [f"{src}split[bg{tag}][fg{tag}]",
            f"[bg{tag}]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},boxblur=20:5[bb{tag}]",
            f"[fg{tag}]scale={W}:{H}:force_original_aspect_ratio=decrease[ff{tag}]",
            f"[bb{tag}][ff{tag}]overlay=(W-w)/2:(H-h)/2,{tail}[v{tag}]"]


def build_filter_graph(clips: list[Clip], pieces: list[Piece], preset: Preset, ass_name: str,
                       include_audio: bool = True) -> str:
    by_id = {c.id: c for c in clips}
    stmts, concat_in = [], ""
    for i, p in enumerate(pieces):
        clip = by_id[p.clip_id]
        stmts += _frame_chain(clip, preset.width, preset.height, str(i))
        concat_in += f"[v{i}]"
        if include_audio:
            if clip.has_audio:
                stmts.append(f"[{i}:a]aresample=48000,aformat=channel_layouts=stereo,"
                             f"asetpts=PTS-STARTPTS[a{i}]")
            else:
                d = _fmt(p.src_end - p.src_start)
                stmts.append(f"anullsrc=r=48000:cl=stereo,atrim=duration={d},asetpts=PTS-STARTPTS[a{i}]")
            concat_in += f"[a{i}]"
    a_flag, a_out = (1, "[ac]") if include_audio else (0, "")
    stmts.append(f"{concat_in}concat=n={len(pieces)}:v=1:a={a_flag}[vc]{a_out}")
    stmts.append(f"[vc]subtitles={ass_name}:fontsdir=fonts[vout]")
    return ";\n".join(stmts)


def build_ffmpeg_cmd(clips: list[Clip], pieces: list[Piece], preset: Preset, ass_name: str,
                     out_name: str, include_audio: bool = True, frame_only: bool = False) -> list[str]:
    by_id = {c.id: c for c in clips}
    cmd: list[str] = []
    for p in pieces:
        cmd += ["-ss", _fmt(p.src_start), "-t", _fmt(p.src_end - p.src_start), "-i", by_id[p.clip_id].path]
    cmd += ["-filter_complex_script", GRAPH_NAME, "-map", "[vout]"]
    if include_audio:
        cmd += ["-map", "[ac]"]
    if frame_only:
        return cmd + ["-frames:v", "1", out_name]
    cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p"]
    if include_audio:
        cmd += ["-c:a", "aac", "-b:a", "160k"]
    return cmd + ["-movflags", "+faststart", out_name]


def _prepare(project: Project, selection: Selection):
    preset = PRESETS[project.preset]
    try:
        pieces = selection_pieces(project.clips, selection)
    except ValueError:
        raise ExportError("selection_invalid",
                          "ช่วงที่เลือกไม่ถูกต้อง หรือไม่มีช่วงที่เปิดใช้งานเหลืออยู่ "
                          "กรุณาตั้งจุดเริ่ม/จบใหม่ และเปิดช่วงที่ถูกตัดอย่างน้อยหนึ่งช่วง") from None
    rendered = [RenderedSub(a, b, s.text, s.x, s.y)
                for a, b, s in subtitles_for_export(project.clips, project.subtitles, selection)]
    return preset, pieces, rendered


def _workdir(preset: Preset, project: Project, rendered, pieces, **graph_kw) -> str:
    wd = tempfile.mkdtemp(prefix="vidcut_")
    Path(wd, "subs.ass").write_text(to_ass(rendered, project.style, (preset.width, preset.height)),
                                    encoding="utf-8")
    Path(wd, GRAPH_NAME).write_text(build_filter_graph(project.clips, pieces, preset, "subs.ass", **graph_kw),
                                    encoding="utf-8")
    shutil.copytree(FONTS_SRC, Path(wd, "fonts"))
    return wd


def _safe_stem(path: str) -> str:
    return re.sub(r'[<>:"/\\|?*\s]+', "_", Path(path).stem).strip("_") or "clip"


def run_export(project: Project, out_dir: str, progress_cb=None, cancel_event=None) -> ExportResult:
    if not project.clips:
        raise ExportError("no_clips", "ยังไม่มีคลิปในโปรเจกต์ กรุณาเพิ่มคลิปก่อน")
    selection = project.selection or Selection(0.0, edited_duration(project.clips))
    preset, pieces, rendered = _prepare(project, selection)
    duration = sum(p.src_end - p.src_start for p in pieces)
    wd = _workdir(preset, project, rendered, pieces)
    try:
        cmd = build_ffmpeg_cmd(project.clips, pieces, preset, "subs.ass", "out.mp4")
        try:
            media.run_ffmpeg(cmd, duration, progress_cb, cancel_event, cwd=wd)
        except FFmpegError as e:
            raise ExportError("export_failed",
                              "ส่งออกวิดีโอไม่สำเร็จ ลองลดช่วงที่เลือก หรือตรวจว่าไฟล์ต้นฉบับยังอยู่",
                              e.details) from e
        except FileNotFoundError as e:
            raise ExportError("ffmpeg_missing", "ไม่พบ ffmpeg กรุณารัน setup.bat อีกครั้ง") from e
        os.makedirs(out_dir, exist_ok=True)
        stem = f"{_safe_stem(project.clips[0].path)}_{preset.name}"
        mp4, srt = os.path.join(out_dir, stem + ".mp4"), os.path.join(out_dir, stem + ".srt")
        shutil.move(os.path.join(wd, "out.mp4"), mp4)
        Path(srt).write_text(to_srt(rendered), encoding="utf-8")
        return ExportResult(mp4, srt)
    finally:
        shutil.rmtree(wd, ignore_errors=True)


def render_preview_frame(project: Project, edited_t: float, out_png: str) -> None:
    """Render one real frame (with subtitles and framing) at the given edited time."""
    total = edited_duration(project.clips)
    t = min(max(0.0, edited_t), max(0.0, total - 0.1))
    preset, pieces, rendered = _prepare(project, Selection(t, min(total, t + 0.1)))
    wd = _workdir(preset, project, rendered, pieces, include_audio=False)
    try:
        cmd = build_ffmpeg_cmd(project.clips, pieces, preset, "subs.ass", "frame.png",
                               include_audio=False, frame_only=True)
        try:
            media.run_ffmpeg(cmd, cwd=wd)
        except FFmpegError as e:
            raise ExportError("preview_failed", "สร้างภาพตัวอย่างไม่สำเร็จ", e.details) from e
        os.makedirs(os.path.dirname(os.path.abspath(out_png)), exist_ok=True)
        shutil.move(os.path.join(wd, "frame.png"), out_png)
    finally:
        shutil.rmtree(wd, ignore_errors=True)
