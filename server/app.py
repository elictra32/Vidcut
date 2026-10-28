"""FastAPI glue. Thin: every real decision lives in core/. Binds to 127.0.0.1 only."""
import copy
import json
import mimetypes
import os
import re
import shutil
import tempfile
import threading
import time
import uuid
import webbrowser
from urllib.parse import urlparse
from dataclasses import asdict
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.background import BackgroundTask
from starlette.middleware.trustedhost import TrustedHostMiddleware

from core import media
from core.autosub import generate_subtitles
from core.encode import AUDIO_KBPS, CONSTANT_QUALITY, CONTAINER_OVERHEAD, _normalized, capped_quality, estimate_bytes, source_video_kbps, video_kbps
from core.align import align as align_audio
from core.cover import CoverError, render_cover, safe_stem, thai_date
from core.vcover import DEFAULT_OUTRO_TEXT, render_vertical_cover
from core.cutmap import pieces_from_dicts
from core.episodes import clip_video_kbps, plan_episodes
from core.export import export_duration, manifest_path, render_preview_frame, run_export
from core.fonts import FONT_FILES
from core.grade import clamp as clamp_grade
from core.media import FFmpegError, color_matrix_of, has_audio_stream, is_browser_playable, is_full_range, make_proxy, probe
from core.models import ROLES, Clip, Keep, Overlay, Project, Selection, project_from_dict, project_to_dict
from core.presets import PRESETS
from core.silence import detect_silences, keeps_from_silences
from core.timeline import cut_points, edited_duration, enabled_keeps
from core.rewrap import rewrap_subtitles
from core.sizing import SAFETY, measure
from core.srt import parse_srt
from core.srt_import import cues_to_subtitles
from core.highlights import LEXICON, find_highlights, find_shots, lines_from_project, transcript_for_ai
from core.timeline import main_clips
from core.waveform import audio_profile, loudness_by_second, waveform_peaks
from server import fake_whisper
from server.errors import AppError, from_exception, payload
from server.jobqueue import JobQueue
from server.jobs import JobRunner
from server.project_store import default_home, load_project, save_project

HOST = "127.0.0.1"
ALLOWED_HOSTS = ("127.0.0.1", "localhost")  # Host/Origin we answer to: blocks DNS rebinding and cross-site POSTs
WEB_DIR = Path(__file__).resolve().parent.parent / "web"
FONTS_DIR = Path(__file__).resolve().parent.parent / "fonts"
BRAND_LOGOS_DIR = Path(__file__).resolve().parent.parent / "assets" / "logos"
TEMP_PREFIXES = ("vidcut_",)


class State:
    def __init__(self, home: str):
        self.home = home
        self.exports = os.path.join(home, "exports")
        self.proxies = os.path.join(home, "proxies")
        self.audio_cache = os.path.join(home, "audio_cache")
        self.covers = os.path.join(home, "covers")
        self.manifests = os.path.join(home, "manifests")
        self.lock = threading.RLock()
        self.project = load_project(home)
        self.jobs = JobRunner(workers=4)
        self.waveforms: dict = {}
        self.loudness: dict = {}
        # desktop mode (server/desktop.py): when the window is closed and nothing is running, the server exits
        self.started = time.time()
        self.last_seen: float | None = None   # last ping from an open page
        self.bye_at: float | None = None      # last time a page said it was closing
        self.quit_requested = False

    def save(self):
        with self.lock:
            save_project(self.project, self.home)

    def clip(self, clip_id: str) -> Clip:
        with self.lock:
            for c in self.project.clips:
                if c.id == clip_id:
                    return c
        raise AppError("clip_not_found", "Clip not found in the project", status=404)


class FreshStaticFiles(StaticFiles):
    """The app's own pages: the browser must re-check them every time, otherwise an updated Vidcut keeps showing the old
    page until a hard refresh."""
    async def get_response(self, path, scope):
        resp = await super().get_response(path, scope)
        resp.headers["Cache-Control"] = "no-cache"
        return resp


def _pick_file(images: bool = False, sound: bool = False) -> str | None:
    override = os.environ.get("VIDCUT_PICK_SOUND_OVERRIDE" if sound else "VIDCUT_PICK_IMAGE_OVERRIDE" if images else "VIDCUT_PICK_OVERRIDE")
    if override:
        return override
    try:
        import tkinter
        from tkinter import filedialog
    except ImportError as e:
        raise AppError("picker_unavailable", "Couldn't open the file picker",
                       "Paste the video file path into the box instead", status=501) from e
    root = tkinter.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    try:
        return filedialog.askopenfilename(
            title="Choose an image" if images else "Choose a sound or video file" if sound else "Choose video",
            filetypes=[("Images", "*.png *.jpg *.jpeg *.webp *.bmp"), ("All files", "*.*")] if images
            else [("Sound or video", "*.mp3 *.wav *.m4a *.aac *.flac *.ogg *.mp4 *.mov *.mkv *.avi *.webm *.m4v"), ("All files", "*.*")] if sound
            else [("Video", "*.mp4 *.mov *.mkv *.avi *.webm *.m4v"), ("All files", "*.*")]) or None
    finally:
        root.destroy()


def _pick_folder() -> str | None:
    override = os.environ.get("VIDCUT_PICK_FOLDER_OVERRIDE")
    if override:
        return override
    try:
        import tkinter
        from tkinter import filedialog
    except ImportError as e:
        raise AppError("picker_unavailable", "Couldn't open the folder picker", "Type the folder path into the box instead", status=501) from e
    root = tkinter.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    try:
        return filedialog.askdirectory(title="Choose a folder for exported files") or None
    finally:
        root.destroy()


def create_app(home: str | None = None) -> FastAPI:
    st = State(home or default_home())
    app = FastAPI(title="Vidcut")
    app.state.st = st
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=list(ALLOWED_HOSTS))

    @app.middleware("http")
    async def refuse_cross_origin_writes(request: Request, call_next):
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            origin = request.headers.get("origin")
            if origin is not None and urlparse(origin).hostname not in ALLOWED_HOSTS:
                err = AppError("forbidden_origin", "This request came from another website and was rejected",
                               "Use Vidcut only through the window opened by run.bat", status=403)
                return JSONResponse({"error": payload(err)}, status_code=403)
        return await call_next(request)

    @app.exception_handler(AppError)
    async def _app_error(_: Request, e: AppError):
        return JSONResponse({"error": payload(e)}, status_code=e.status)

    @app.exception_handler(Exception)
    async def _unexpected(_: Request, e: Exception):
        ae = from_exception(e)
        return JSONResponse({"error": payload(ae)}, status_code=ae.status)

    # ---- project -------------------------------------------------------------------------
    @app.get("/api/project")
    def get_project():
        with st.lock:
            return {"project": project_to_dict(st.project),
                    "presets": {k: asdict(v) for k, v in PRESETS.items()},
                    "fonts": list(FONT_FILES)}

    @app.get("/api/ping")
    def get_ping():
        """Pages ping every few seconds; also how a second launch learns that Vidcut is already running."""
        st.last_seen = time.time()
        return {"app": "vidcut", "busy": st.jobs.active(ignore=("proxy",)) > 0}

    @app.post("/api/bye")
    def post_bye():
        st.bye_at = time.time()
        return {"ok": True}

    @app.post("/api/quit")
    def post_quit():
        """Quit Vidcut completely, even with jobs running (queued exports continue the next time it opens)."""
        st.save()
        st.quit_requested = True
        return {"ok": True}

    @app.post("/api/project/beacon")
    def post_project_beacon(body: dict):
        """The same save as PUT, for navigator.sendBeacon when the page is closing (beacons can only POST)."""
        return put_project(body)

    @app.put("/api/project")
    def put_project(body: dict):
        try:
            proj = project_from_dict(body)
            if proj.preset not in PRESETS:
                raise ValueError("preset")
        except (TypeError, KeyError, ValueError) as e:
            raise AppError("project_invalid", "Invalid project data", "Refresh the page and try again",
                           str(e), status=422) from e
        with st.lock:
            if proj.rev != st.project.rev:
                raise AppError("project_stale", "The data on this page is out of date (a background job just finished)",
                               "The latest data was reloaded. Try your edit again", status=409)
            # The page owns keeps/framing/role/subtitles/style/selection. Everything about the media itself
            # (path, proxy, size, duration) is the server's, and clips only enter through /api/clips.
            current = {c.id: c for c in st.project.clips}
            clips = []
            for c in proj.clips:
                known = current.get(c.id)
                if known is not None:
                    known.keeps, known.framing = c.keeps, c.framing
                    known.grade = clamp_grade(c.grade)
                    known.role = c.role if c.role in ROLES else "main"
                    known.cuts_confirmed = bool(c.cuts_confirmed)
                    clips.append(known)
            proj.clips = clips
            known_ov = {o.id: o for o in st.project.overlays}
            overlays = []
            for o in proj.overlays:  # the page owns placement; the image file itself is the server's
                k = known_ov.get(o.id)
                if k is not None:
                    k.x, k.y = min(1.0, max(0.0, o.x)), min(1.0, max(0.0, o.y))
                    k.width, k.opacity = min(1.0, max(0.02, o.width)), min(1.0, max(0.0, o.opacity))
                    k.start, k.end = o.start, o.end
                    overlays.append(k)
            proj.overlays = overlays
            proj.export.out_dir = st.project.export.out_dir  # where files get written is chosen via /api/export-folder
            proj.subtitles = [s for s in proj.subtitles if s.clip_id in current]
            st.project = proj
            st.save()
            return {"ok": True, "rev": st.project.rev}

    # ---- clips ---------------------------------------------------------------------------
    def add_clip(path: str) -> dict:
        path = os.path.abspath(path)
        if not os.path.isfile(path):
            raise AppError("file_missing", "File not found", "Check that the file is still in its original location", path, status=404)
        try:
            info = probe(path)
        except FFmpegError as e:
            raise AppError("unreadable_media", "This video file is damaged or unreadable",
                           "Try opening it in a video player first, or convert the file", e.details) from e
        clip = Clip(id=uuid.uuid4().hex[:8], path=path, duration=info["duration"], width=info["width"],
                    height=info["height"], fps=info["fps"], has_audio=info["has_audio"],
                    keeps=[Keep(0.0, info["duration"])], color_matrix=color_matrix_of(info), full_range=is_full_range(info),
                    cuts_confirmed=True)  # nothing to review until dead air is detected: an already-edited file goes straight on
        with st.lock:
            st.project.clips.append(clip)
            st.project.rev += 1
            st.save()
        # decode the audio overview now, in the background, so the waveform and the highlight scan are instant later
        threading.Thread(target=lambda: audio_profile(path, st.audio_cache), daemon=True).start()
        job = None
        if not is_browser_playable(info):
            os.makedirs(st.proxies, exist_ok=True)
            out = os.path.join(st.proxies, f"{clip.id}.mp4")

            def work(progress, cancel):
                make_proxy(path, out, progress, cancel)
                with st.lock:
                    st.clip(clip.id).proxy_path = out
                    st.project.rev += 1
                    st.save()
                return {"proxy_path": out}
            job = st.jobs.submit(work, "proxy", pool="proxy")
        return {"clip": asdict(clip), "job": job}

    @app.post("/api/clips")
    def post_clip(body: dict):
        return add_clip(str(body.get("path", "")))

    @app.post("/api/clips/pick")
    def pick_clip():
        path = _pick_file()
        return add_clip(path) if path else {"clip": None, "job": None}

    @app.post("/api/clips/{clip_id}/silence")
    def post_silence(clip_id: str, body: dict | None = None):
        body = body or {}
        clip = st.clip(clip_id)
        path, duration = clip.path, clip.duration
        noise_db, min_silence = float(body.get("noise_db", -35.0)), float(body.get("min_silence", 0.6))
        padding = float(body.get("padding", 0.15))

        def work(progress, cancel):
            sil = detect_silences(path, duration, noise_db, min_silence, progress, cancel)
            keeps = keeps_from_silences(sil, duration, padding) or [Keep(0.0, duration)]
            with st.lock:
                st.clip(clip_id).keeps = keeps
                st.clip(clip_id).cuts_confirmed = False  # fresh detection: ask for review again
                st.project.rev += 1
                st.save()
            return {"keeps": [asdict(k) for k in keeps]}
        return {"job": st.jobs.submit(work, "silence")}

    @app.get("/api/clips/{clip_id}/waveform")
    def get_waveform(clip_id: str, points: int = 2000):
        clip = st.clip(clip_id)
        key = (clip_id, points)
        if key not in st.waveforms:
            st.waveforms[key] = waveform_peaks(clip.path, points, st.audio_cache)
        return {"peaks": st.waveforms[key]}

    @app.get("/media/{clip_id}")
    def get_media(clip_id: str):
        clip = st.clip(clip_id)
        path = clip.proxy_path if clip.proxy_path and os.path.exists(clip.proxy_path) else clip.path
        if not os.path.isfile(path):
            raise AppError("file_missing", "Original file not found", "Check that the file is still in its original location", status=404)
        return FileResponse(path, media_type=mimetypes.guess_type(path)[0] or "video/mp4")

    # ---- logo / photo overlays -------------------------------------------------------------
    IMAGE_EXT = (".png", ".jpg", ".jpeg", ".webp", ".bmp")

    def add_overlay(path: str) -> dict:
        path = os.path.abspath(path)
        if not os.path.isfile(path):
            raise AppError("file_missing", "File not found", "Check that the file is still in its original location", path, status=404)
        if not path.lower().endswith(IMAGE_EXT):
            raise AppError("not_an_image", "This isn't a supported image", "Use a PNG, JPG, WebP or BMP file", status=400)
        try:
            info = probe(path)
        except FFmpegError as e:
            raise AppError("unreadable_media", "This image is damaged or unreadable",
                           "Try opening it in an image viewer first", e.details) from e
        overlay = Overlay(id=uuid.uuid4().hex[:8], path=path)
        with st.lock:
            st.project.overlays.append(overlay)
            st.project.rev += 1
            st.save()
        return {"overlay": asdict(overlay), "width": info["width"], "height": info["height"]}

    def brand_logo_files() -> list[str]:
        return sorted(f for f in os.listdir(BRAND_LOGOS_DIR) if f.lower().endswith(".png") and not f.startswith("_")) if BRAND_LOGOS_DIR.is_dir() else []

    @app.get("/api/brand-logos")
    def get_brand_logos():
        """The THUS logos shipped with Vidcut (assets/logos): file names, to offer in the Logo / photo panel."""
        return {"files": brand_logo_files()}

    @app.post("/api/overlays")
    def post_overlay(body: dict):
        if body.get("brand"):
            files = brand_logo_files()
            # only the shipped files: never a path from the page (a different letter case is still the same file on Windows)
            name = next((f for f in files if f.lower() == os.path.basename(str(body["brand"])).lower()), None)
            if name is None:
                raise AppError("file_missing", "That logo isn't in the Vidcut logo folder",
                               f"Vidcut looked in {BRAND_LOGOS_DIR} and found {len(files)} logo file(s). "
                               "If that is not the folder you expect, close Vidcut completely (Quit) and open it again", status=404)
            result = add_overlay(str(BRAND_LOGOS_DIR / name))
            if body.get("replace"):
                # picking another colour/shape swaps the earlier brand logo (it keeps its position, size and timing)
                with st.lock:
                    new = next(o for o in st.project.overlays if o.id == result["overlay"]["id"])
                    old = [o for o in st.project.overlays if o is not new and os.path.dirname(o.path) == str(BRAND_LOGOS_DIR)]
                    if old:
                        keep = old[0]
                        new.x, new.y, new.width, new.opacity, new.start, new.end = keep.x, keep.y, keep.width, keep.opacity, keep.start, keep.end
                        st.project.overlays = [o for o in st.project.overlays if o not in old]
                        st.save()
                        result["overlay"] = asdict(new)
            return result
        return add_overlay(str(body.get("path", "")))

    @app.post("/api/overlays/pick")
    def pick_overlay():
        path = _pick_file(images=True)
        return add_overlay(path) if path else {"overlay": None}

    @app.delete("/api/overlays/{overlay_id}")
    def delete_overlay(overlay_id: str):
        with st.lock:
            before = len(st.project.overlays)
            st.project.overlays = [o for o in st.project.overlays if o.id != overlay_id]
            if len(st.project.overlays) == before:
                raise AppError("overlay_not_found", "Overlay not found", status=404)
            st.project.rev += 1
            st.save()
        return {"ok": True}

    @app.get("/overlay-media/{overlay_id}")
    def get_overlay_media(overlay_id: str):
        with st.lock:
            o = next((x for x in st.project.overlays if x.id == overlay_id), None)
        if o is None or not os.path.isfile(o.path):
            raise AppError("file_missing", "Image not found", status=404)
        return FileResponse(o.path, media_type=mimetypes.guess_type(o.path)[0] or "image/png")

    # ---- highlights ----------------------------------------------------------------------------
    def edited_loudness(snap: Project) -> list[float]:
        """RMS per second along the edited timeline (approximate to the second)."""
        out: list[float] = []
        for c in main_clips(snap.clips):
            key = (c.id, c.path)
            if key not in st.loudness:
                st.loudness[key] = loudness_by_second(c.path, st.audio_cache)
            per_s = st.loudness[key]
            for k in enabled_keeps(c):
                out += per_s[int(k.start): max(int(k.start) + 1, int(round(k.end)))]
        return out

    @app.post("/api/highlights")
    def post_highlights(body: dict | None = None):
        body = body or {}
        with st.lock:
            snap = copy.deepcopy(st.project)
        lines = lines_from_project(snap.clips, snap.subtitles)
        if not lines:
            raise AppError("no_subtitles", "There are no subtitles to analyse",
                           "Generate or import subtitles first (for the part you want to scan)")
        lexicon = {k: [str(w) for w in v] for k, v in (body.get("lexicon") or {}).items() if k in LEXICON}
        if body.get("mode") == "shots":   # every short moment around the telling words, for a highlight reel
            cands = find_shots(lines, edited_loudness(snap), lexicon=lexicon or None, pad_s=float(body.get("pad_s", 1.5)),
                               merge_gap_s=float(body.get("merge_gap_s", 6)), min_hits=int(body.get("min_hits", 1)))
        else:
            cands = find_highlights(lines, edited_loudness(snap), min_s=float(body.get("min_s", 30)), max_s=float(body.get("max_s", 90)),
                                    per_category=int(body.get("per_category", 5)), lexicon=lexicon or None)
        return {"candidates": [{"start": c.start, "end": c.end, "duration": c.duration, "category": c.category, "label": c.label,
                                "score": round(c.score, 2), "hits": c.hits, "text": c.text[:160]} for c in cands],
                "lexicon": {k: lexicon.get(k, LEXICON[k]) for k in LEXICON}}

    @app.get("/api/highlights/lexicon")
    def get_highlights_lexicon():
        return {"lexicon": LEXICON}

    @app.get("/api/highlights/transcript")
    def get_highlights_transcript():
        with st.lock:
            snap = copy.deepcopy(st.project)
        lines = lines_from_project(snap.clips, snap.subtitles)
        if not lines:
            raise AppError("no_subtitles", "There are no subtitles to export", "Generate or import subtitles first")
        return {"text": transcript_for_ai(lines), "lines": len(lines)}

    # ---- captions made for the ORIGINAL video, but the clip here is a cut version of it ------------------------
    @app.get("/api/clips/{clip_id}/cut-manifest")
    def get_cut_manifest(clip_id: str):
        """The cut map Vidcut saved when it exported this clip (see core/export.write_cut_manifest), if there is one."""
        clip = st.clip(clip_id)
        # kept in Vidcut's own folder (matched by file name and size); a copy next to the video works too
        path = manifest_path(clip.path, st.manifests)
        if not os.path.isfile(path):
            path = manifest_path(clip.path)
        if not os.path.isfile(path):
            return {"found": False}
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            if data.get("bytes") and os.path.isfile(clip.path) and data["bytes"] != os.path.getsize(clip.path):
                return {"found": False}  # a different file with the same name
            sources = [{"name": s["name"], "role": s.get("role", "main"), "pieces": s["pieces"]} for s in data["sources"]]
            pieces_from_dicts(sources[0]["pieces"] if sources else [])
        except (OSError, ValueError, KeyError, TypeError, IndexError):
            return {"found": False, "damaged": True}
        sources.sort(key=lambda s: s["role"] != "main")
        return {"found": True, "sources": sources}

    @app.post("/api/pick-original")
    def pick_original():
        path = _pick_file()
        return {"path": path}

    @app.post("/api/clips/{clip_id}/align")
    def post_align(clip_id: str, body: dict):
        clip = st.clip(clip_id)
        original = os.path.abspath(str(body.get("original_path", "")))
        if not os.path.isfile(original):
            raise AppError("file_missing", "File not found", "Check that the file is still in its original location", original, status=404)
        cut_path = clip.path

        def work(progress, cancel):
            res = align_audio(cut_path, original, progress, cancel)
            if not res.pieces:
                raise AppError("align_failed", "Couldn't find this video's audio in the original",
                               "Check that this is the cut version of that same video, with the original audio")
            return {"pieces": [{"src_start": p.src_start, "src_end": p.src_end, "out_start": p.out_start} for p in res.pieces],
                    "coverage": round(res.coverage, 3), "confidence": round(res.confidence, 3)}
        return {"job": st.jobs.submit(work, "align")}

    # ---- subtitles from an SRT file (e.g. YouTube auto captions) -----------------------------
    @app.post("/api/subtitles/import-srt")
    def import_srt(body: dict):
        clip_id = str(body.get("clip_id", ""))
        offset = float(body.get("offset", 0.0))
        only_selection = bool(body.get("only_selection", True))
        cues = parse_srt(str(body.get("srt_text", "")))
        if not cues:
            raise AppError("srt_empty", "No subtitles found in this file", "It must be an .srt, .vtt or .sbv file (UTF-8), e.g. downloaded from YouTube Studio")
        st.clip(clip_id)  # 404 when unknown
        with st.lock:
            snap = copy.deepcopy(st.project)
        if only_selection and snap.selection is None:
            raise AppError("no_selection", "No range selected for the import",
                           "Set In/Out first, or import the whole file")
        cutmap = None
        if body.get("pieces"):
            try:
                cutmap = pieces_from_dicts(body["pieces"])
            except (KeyError, TypeError, ValueError) as e:
                raise AppError("cutmap_invalid", "The cut information is not valid", "Pick the cut file or the original video again") from e
        subs = cues_to_subtitles(snap.clips, clip_id, cues, PRESETS[snap.preset], offset,
                                 snap.selection if only_selection else None, cutmap)
        if not subs:
            raise AppError("srt_no_match", "No subtitles match this clip's time range",
                           "Check that the same original file was uploaded to YouTube, try the time shift, or import the whole file")
        with st.lock:
            st.project.subtitles = [x for x in st.project.subtitles if x.clip_id != clip_id] + subs
            st.project.rev += 1
            st.save()
        return {"count": len(subs)}

    @app.post("/api/subtitles/rewrap")
    def post_rewrap(body: dict):
        """Re-flow every subtitle to N characters per line (and at most M lines)."""
        try:
            width, lines = int(body.get("max_chars")), int(body.get("max_lines", 2))
        except (TypeError, ValueError) as e:
            raise AppError("rewrap_invalid", "Enter the characters per line as a number") from e
        if not (4 <= width <= 80 and 1 <= lines <= 4):
            raise AppError("rewrap_invalid", "Characters per line must be 4–80 and lines 1–4")
        with st.lock:
            before = len(st.project.subtitles)
            st.project.subtitles = rewrap_subtitles(st.project.subtitles, width, lines)
            st.project.rev += 1
            st.save()
            return {"before": before, "after": len(st.project.subtitles)}

    # ---- transcribe / export -------------------------------------------------------------
    @app.post("/api/transcribe")
    def post_transcribe(body: dict | None = None):
        model = (body or {}).get("model", "large-v3")
        with st.lock:
            snap = copy.deepcopy(st.project)
        if snap.selection is None:
            raise AppError("no_selection", "No range selected for transcription",
                           "Set start/end (In/Out) on the timeline first")
        factory = fake_whisper.factory if os.environ.get("VIDCUT_FAKE_WHISPER") == "1" else None

        def work(progress, cancel):
            progress(0.0, "Preparing audio and loading the model (first use downloads it)")
            subs = generate_subtitles(snap.clips, snap.selection, snap.preset, model, progress, cancel, factory)
            with st.lock:
                st.project.subtitles = subs
                st.project.rev += 1
                st.save()
            return {"count": len(subs), "empty": not subs}
        return {"job": st.jobs.submit(work, "transcribe")}

    @app.post("/api/export")
    def post_export(body: dict | None = None):
        preset = (body or {}).get("preset")
        if preset is not None and preset not in PRESETS:
            raise AppError("preset_unknown", "Unknown preset")
        with st.lock:
            if preset:
                st.project.preset = preset
                st.save()
            snap = copy.deepcopy(st.project)

        return {"job": st.jobs.submit(lambda progress, cancel: run_single_export(snap, progress, cancel), "export")}

    def clean_title(raw) -> str:
        """A cover title keeps the line breaks the user typed; each line is tidied and empty lines are dropped."""
        return "\n".join(l for l in (" ".join(line.split()) for line in str(raw or "").splitlines()) if l)

    # ---- episode covers made from the THUS intro template ------------------------------------------
    @app.post("/api/covers")
    def post_covers(body: dict):
        """Make one intro clip per title from a template cover, add them as Intro clips (in order)."""
        items = body.get("items") or []
        if not (1 <= len(items) <= 50):
            raise AppError("covers_invalid", "Give between 1 and 50 titles")
        titles = []
        for it in items:
            t = clean_title(it.get("title", ""))
            if not t or len(t.replace("\n", " ")) > 120 or t.count("\n") > 3:
                raise AppError("covers_invalid", "Each title must be 1–120 characters, in at most 4 lines")
            titles.append((t, str(it.get("date_text") or "").strip()))
        vertical = body.get("format") == "vertical"
        if vertical:
            template = ""   # drawn from scratch: there is no vertical original to copy
        elif body.get("template_clip_id"):
            template = st.clip(str(body["template_clip_id"])).path
        else:
            template = os.path.abspath(str(body.get("template_path", "")))
        if not vertical and not os.path.isfile(template):
            raise AppError("file_missing", "Template file not found", "Choose the cover clip to copy the look from", template, status=404)
        default_date = str(body.get("date_text") or "").strip()
        if not default_date:
            import datetime
            try:
                d = datetime.date.fromisoformat(str(body.get("date") or "")) if body.get("date") else datetime.date.today()
            except ValueError as e:
                raise AppError("covers_invalid", "The date is not valid", "Use the date picker or type the date text") from e
            default_date = thai_date(d.year, d.month, d.day)
        title_font, date_font = str(body.get("title_font") or "Montserrat"), str(body.get("date_font") or "Sarabun")
        outro_font = str(body.get("outro_font") or "Prompt Light")

        def sound_of(key):   # a clip already in the project, or any sound/video file picked from the disk
            raw = body.get(key)
            if not raw:
                return None
            raw = str(raw)
            if raw.startswith("file:"):
                path = os.path.abspath(raw[5:])
                if not os.path.isfile(path):
                    raise AppError("file_missing", "The sound file was not found", "Choose it again", path, status=404)
                if not has_audio_stream(path):
                    raise AppError("sound_no_audio", "That file has no sound to use", "Pick a file that has sound, or silence")
                return path
            clip = st.clip(raw)
            if not clip.has_audio:
                raise AppError("sound_no_audio", "That clip has no sound to use", "Pick a clip that has sound, or silence")
            return clip.path
        intro_sound, outro_sound = sound_of("intro_sound_clip_id"), sound_of("outro_sound_clip_id")
        replace = bool(body.get("replace_intros", True))

        def work(progress, cancel):
            os.makedirs(st.covers, exist_ok=True)
            made = []
            for i, (title, date_text) in enumerate(titles):
                progress(i / len(titles), f"Cover {i + 1}/{len(titles)}: {title}")
                stem, n = safe_stem(title.replace("\n", " ")) + ("_vertical" if vertical else ""), 1
                while os.path.exists(os.path.join(st.covers, f"{stem}{'' if n == 1 else f'_{n}'}.mp4")):
                    n += 1
                out = os.path.join(st.covers, f"{stem}{'' if n == 1 else f'_{n}'}.mp4")
                try:
                    if vertical:
                        render_vertical_cover("intro", out, title=title, date_text=date_text or default_date, title_font=title_font,
                                              date_font=date_font, cancel=cancel, sound=intro_sound)
                    else:
                        render_cover(template, title, date_text or default_date, out, title_font=title_font, date_font=date_font, cancel=cancel)
                except CoverError as e:
                    raise AppError(e.code, e.message, "", e.details) from e
                made.append(out)
            outro_file = None
            if vertical and body.get("with_outro"):
                outro_file = os.path.join(st.covers, "THUS_outro_vertical.mp4")
                try:
                    render_vertical_cover("outro", outro_file, outro_text=str(body.get("outro_text") or DEFAULT_OUTRO_TEXT)[:300],
                                          outro_font=outro_font, cancel=cancel, sound=outro_sound)
                except CoverError as e:
                    raise AppError(e.code, e.message, "", e.details) from e
            clips = []
            for out, role in [(m, "intro") for m in made] + ([(outro_file, "outro")] if outro_file else []):
                info = probe(out)
                clips.append(Clip(id=uuid.uuid4().hex[:8], path=out, duration=info["duration"], width=info["width"], height=info["height"],
                                  fps=info["fps"], has_audio=info["has_audio"], keeps=[Keep(0.0, info["duration"])], role=role))
            with st.lock:
                if replace:
                    roles = {"intro"} | ({"outro"} if outro_file else set())
                    gone = {c.id for c in st.project.clips if c.role in roles}
                    st.project.clips = [c for c in st.project.clips if c.id not in gone]
                    st.project.subtitles = [s for s in st.project.subtitles if s.clip_id not in gone]
                st.project.clips.extend(clips)
                st.project.rev += 1
                st.save()
            progress(1.0, "Done")
            return {"count": len(made), "dir": st.covers, "names": [os.path.basename(p) for p in made], "outro": bool(outro_file)}
        return {"job": st.jobs.submit(work, "covers")}

    @app.post("/api/covers/pick-sound")
    def post_pick_sound():
        """Let the user choose any sound or video file to use as a cover's sound (its audio is taken from the start)."""
        path = _pick_file(sound=True)
        if not path:
            return {"path": None}
        try:
            has_audio = has_audio_stream(path)
        except FFmpegError as e:
            raise AppError("unreadable_media", "This file is damaged or unreadable", "Try another file", e.details) from e
        if not has_audio:
            raise AppError("sound_no_audio", "That file has no sound to use", "Pick a file that has sound")
        return {"path": os.path.abspath(path), "name": os.path.basename(path)}

    @app.post("/api/covers/preview")
    def post_covers_preview(body: dict):
        """One quick PNG of a cover with the chosen text and fonts, so they can be judged before making the clips."""
        title = clean_title(body.get("title"))[:120] or "Episode title"
        date_text = str(body.get("date_text") or "").strip() or "วันที่ 1 มกราคม  2570"
        kind = "outro" if body.get("kind") == "outro" else "intro"
        title_font, date_font = str(body.get("title_font") or "Montserrat"), str(body.get("date_font") or "Prompt Light")
        work_dir = tempfile.mkdtemp(prefix="vidcut_cp_")
        out = os.path.join(work_dir, "cover.png")
        try:
            if body.get("format") == "vertical":
                render_vertical_cover(kind, out, title=title, date_text=date_text, title_font=title_font, date_font=date_font,
                                      outro_font=str(body.get("outro_font") or "Prompt Light"),
                                      outro_text=str(body.get("outro_text") or DEFAULT_OUTRO_TEXT)[:300], still_at=2.4)
            else:
                if body.get("template_clip_id"):
                    template = st.clip(str(body["template_clip_id"])).path
                else:
                    template = os.path.abspath(str(body.get("template_path", "")))
                if not os.path.isfile(template):
                    raise AppError("file_missing", "Template file not found", "Choose the cover clip to copy the look from", template, status=404)
                render_cover(template, title, date_text, out, title_font=title_font, date_font=date_font, still_at=2.4)
        except CoverError as e:
            shutil.rmtree(work_dir, ignore_errors=True)
            raise AppError(e.code, e.message, "", e.details) from e
        except Exception:
            shutil.rmtree(work_dir, ignore_errors=True)
            raise
        return FileResponse(out, media_type="image/png", background=BackgroundTask(shutil.rmtree, work_dir, True))

    # ---- split into episodes (each under a size limit, own intro, shared outro) ---------------------
    def episode_plan(snap: Project, max_mb: float, measured_kbps: float | None = None):
        if max_mb < 5:
            raise AppError("episode_limit_too_small", "The size limit is too small", "Use at least 5 MB per episode")
        sel = snap.selection or Selection(0.0, edited_duration(snap.clips))
        if sel.end - sel.start <= 0:
            raise AppError("no_clips", "No clips in the project", "Add a clip first")

        def length(c):
            return sum(k.end - k.start for k in enabled_keeps(c))
        intros = [(c.id, length(c)) for c in snap.clips if c.role == "intro" and length(c) > 0]
        outro = sum(length(c) for c in snap.clips if c.role == "outro")
        try:
            eps = plan_episodes(cut_points(snap.clips), sel.start, sel.end, max_bytes=max_mb * 1048576,
                                source_kbps=source_video_kbps(snap.clips), preset=snap.preset,
                                container=_normalized(snap.export).container, intros=intros, outro_dur=outro,
                                measured_kbps=measured_kbps)
        except ValueError as e:
            raise AppError("episode_limit_too_small", "The size limit is too small for these intro/outro clips",
                           "Raise the limit or use shorter intro/outro clips") from e
        return eps, len(intros)

    def episode_json(e) -> dict:
        return {"index": e.index, "start": e.start, "end": e.end, "duration": e.duration, "intro_clip_id": e.intro_clip_id,
                "video_kbps": e.video_kbps, "est_bytes": e.est_bytes, "max_bytes": e.max_bytes}

    def prepare_episodes(snap: Project, max_mb: float, chosen, measured_kbps: float | None = None):
        """The episode plan for `snap`, with the page's own intro choices applied (one clip id per episode)."""
        eps, _ = episode_plan(snap, max_mb, measured_kbps)
        if chosen is not None:
            valid = {c.id for c in snap.clips if c.role == "intro"}
            if len(chosen) != len(eps) or any(i not in valid for i in chosen if i):
                raise AppError("intro_choice_invalid", "The intro choice doesn't match the episodes", "Plan the episodes again")
            for e, i in zip(eps, chosen):
                e.intro_clip_id = i or None
        snap.export.quality = capped_quality(snap.export.quality)  # constant quality, capped per episode so each stays under the limit
        return eps

    def run_single_export(snap: Project, progress, cancel) -> dict:
        out_dir = snap.export.out_dir or st.exports
        res = run_export(snap, out_dir, progress, cancel, manifest_dir=st.manifests)
        return {"video": os.path.basename(res.video), "srt": os.path.basename(res.srt) if res.srt else None, "dir": out_dir,
                "downloadable": os.path.abspath(out_dir) == os.path.abspath(st.exports)}

    def run_episode_set(snap: Project, eps, max_mb: float, progress, cancel) -> dict:
        out_dir = snap.export.out_dir or st.exports
        files = []
        total = sum(e.duration for e in eps)
        done = 0.0
        for e in eps:
            base, span = done / total, e.duration / total

            def report(f, m="", base=base, span=span, e=e):
                progress(base + span * f, f"Episode {e.index}/{len(eps)} · {m}" if m else f"Episode {e.index}/{len(eps)}")
            intro = next((c for c in snap.clips if c.id == e.intro_clip_id), None)
            res = run_export(snap, out_dir, report, cancel, selection=Selection(e.start, e.end),
                             intro_ids=[e.intro_clip_id] if e.intro_clip_id else None,
                             name_suffix=f"_EP{e.index:02d}", max_video_kbps=e.video_kbps, manifest_dir=st.manifests,
                             name=Path(intro.path).stem if intro else None)  # an episode is named after its cover
            size = os.path.getsize(res.video)
            files.append({"video": os.path.basename(res.video), "bytes": size, "over_limit": size > max_mb * 1048576})
            done += e.duration
        return {"files": files, "dir": out_dir, "limit_mb": max_mb,
                "downloadable": os.path.abspath(out_dir) == os.path.abspath(st.exports)}

    def highlight_caps(snap: Project, ranges: list[dict], with_extras: bool, max_mb) -> list[int | None]:
        """Bitrate cap per highlight so that each file stays under `max_mb` (None = no limit)."""
        if not max_mb:
            return [None] * len(ranges)
        max_mb = float(max_mb)
        if max_mb < 1:
            raise AppError("clip_limit_too_small", "The size limit is too small", "Use at least 1 MB per clip")

        def length(c):
            return sum(k.end - k.start for k in enabled_keeps(c))
        extras = (max((length(c) for c in snap.clips if c.role == "intro"), default=0.0)
                  + sum(length(c) for c in snap.clips if c.role == "outro")) if with_extras else 0.0
        src, container = source_video_kbps(snap.clips), _normalized(snap.export).container
        try:
            return [clip_video_kbps(max_mb * 1048576, r["end"] - r["start"] + extras, source_kbps=src, preset=snap.preset, container=container)
                    for r in ranges]
        except ValueError as e:
            raise AppError("clip_limit_too_small", "The size limit is too small for the longest clip",
                           "Raise the limit, or pick shorter highlights") from e

    def run_highlight_set(snap: Project, ranges: list[dict], with_extras: bool, progress, cancel, max_mb=None) -> dict:
        """One finished file per picked highlight, each cut from the same edit with the same style."""
        out_dir = snap.export.out_dir or st.exports
        caps = highlight_caps(snap, ranges, with_extras, max_mb)
        if max_mb:
            snap.export.quality = capped_quality(snap.export.quality)   # constant quality, capped per clip so each stays under the limit
        total = sum(r["end"] - r["start"] for r in ranges)
        given = (snap.export.filename or "").strip()
        files, done = [], 0.0
        for i, r in enumerate(ranges, 1):
            base, span = done / total, (r["end"] - r["start"]) / total

            def report(f, m="", base=base, span=span, i=i):
                progress(base + span * f, f"Highlight {i}/{len(ranges)} · {m}" if m else f"Highlight {i}/{len(ranges)}")
            label = re.sub(r"[^A-Za-z0-9]+", "", r.get("label") or "")
            res = run_export(snap, out_dir, report, cancel, selection=Selection(r["start"], r["end"]),
                             intro_ids=None if with_extras else [], with_extras=with_extras, manifest_dir=st.manifests, max_video_kbps=caps[i - 1],
                             name_suffix=f"_HL{i:02d}{('_' + label) if label else ''}", name=f"{given}_HL{i:02d}" if given else None)
            size = os.path.getsize(res.video)
            files.append({"video": os.path.basename(res.video), "bytes": size, "over_limit": bool(max_mb) and size > float(max_mb) * 1048576})
            done += r["end"] - r["start"]
        return {"files": files, "dir": out_dir, "kind": "highlights",
                "downloadable": os.path.abspath(out_dir) == os.path.abspath(st.exports)}

    def clean_ranges(snap: Project, raw) -> list[dict]:
        total = edited_duration(snap.clips)
        out = []
        for r in raw or []:
            try:
                a, b = float(r["start"]), float(r["end"])
            except (KeyError, TypeError, ValueError):
                raise AppError("highlights_invalid", "A highlight range is not valid", "Pick the highlights again") from None
            a, b = max(0.0, a), min(total, b)
            if b - a >= 0.5:
                out.append({"start": a, "end": b, "label": str(r.get("label") or "")[:30]})
        if not out or len(out) > 100:
            raise AppError("highlights_invalid", "Pick between 1 and 100 highlights inside the timeline", "Pick the highlights again")
        return out

    # ---- the job queue: long jobs that run one after another and survive closing the app ------------
    def queue_export(project_dict: dict, params: dict, progress, cancel) -> dict:
        return run_single_export(project_from_dict(project_dict), progress, cancel)

    def queue_episodes(project_dict: dict, params: dict, progress, cancel) -> dict:
        snap = project_from_dict(project_dict)
        max_mb = float(params.get("max_mb", 500))
        return run_episode_set(snap, prepare_episodes(snap, max_mb, params.get("intro_ids"), params.get("measured_kbps")), max_mb, progress, cancel)

    def queue_highlights(project_dict: dict, params: dict, progress, cancel) -> dict:
        snap = project_from_dict(project_dict)
        return run_highlight_set(snap, clean_ranges(snap, params.get("ranges")), bool(params.get("with_extras", False)), progress, cancel,
                                 params.get("max_mb"))

    st.queue = JobQueue(st.home, {"export": queue_export, "episodes": queue_episodes, "highlights": queue_highlights},
                        busy=lambda: st.jobs.active(ignore=("proxy",)) > 0)
    st.queue.start()  # items left over from the last run (when the app was closed) continue now

    def describe(snap: Project) -> str:
        names = [os.path.basename(c.path) for c in snap.clips if c.role == "main"]
        what = names[0] if len(names) == 1 else f"{len(names)} clips" if names else "project"
        if snap.selection:
            m = lambda t: f"{int(t // 60)}:{int(t % 60):02d}"
            return f"{what} · {m(snap.selection.start)}–{m(snap.selection.end)}"
        return f"{what} · whole timeline"

    @app.get("/api/queue")
    def get_queue():
        return st.queue.snapshot()

    @app.post("/api/queue")
    def post_queue(body: dict):
        kind = str(body.get("kind", ""))
        if kind not in ("export", "episodes", "highlights"):
            raise AppError("queue_invalid", "This can't be queued", "Only exports, episode batches and highlight batches can be queued")
        params = dict(body.get("params") or {})
        preset = params.get("preset")
        if preset is not None and preset not in PRESETS:
            raise AppError("preset_unknown", "Unknown preset")
        with st.lock:
            snap = copy.deepcopy(st.project)
        if preset:
            snap.preset = preset
        if not snap.clips:
            raise AppError("no_clips", "No clips in the project", "Add a clip first")
        if kind == "export":
            try:
                export_duration(snap)  # refuse an unusable selection now, not when its turn comes
            except ValueError as e:
                raise from_exception(e) from e
            label = f"Export · {describe(snap)}"
        elif kind == "highlights":
            params["ranges"] = clean_ranges(snap, params.get("ranges"))   # validates now, and drops anything outside the timeline
            highlight_caps(snap, params["ranges"], bool(params.get("with_extras", False)), params.get("max_mb"))
            label = f"{len(params['ranges'])} highlight clips · {describe(snap).split(' · ')[0]}"
        else:
            prepare_episodes(copy.deepcopy(snap), float(params.get("max_mb", 500)), params.get("intro_ids"), params.get("measured_kbps"))  # validates now
            label = f"Episodes (≤ {float(params.get('max_mb', 500)):g} MB) · {describe(snap)}"
        return st.queue.add(kind, label, params, project_to_dict(snap))

    @app.post("/api/queue/pause")
    def post_queue_pause():
        st.queue.set_paused(True)
        return st.queue.snapshot()

    @app.post("/api/queue/resume")
    def post_queue_resume():
        st.queue.set_paused(False)
        return st.queue.snapshot()

    @app.post("/api/queue/clear-finished")
    def post_queue_clear():
        return {"removed": st.queue.clear_finished()}

    @app.post("/api/queue/{item_id}/cancel")
    def post_queue_cancel(item_id: str):
        if not st.queue.cancel(item_id):
            raise AppError("queue_item_not_found", "That queue item can't be cancelled", status=404)
        return {"ok": True}

    @app.post("/api/queue/{item_id}/move")
    def post_queue_move(item_id: str, body: dict):
        if not st.queue.move(item_id, -1 if int(body.get("delta", 0)) < 0 else 1):
            raise AppError("queue_item_not_found", "That item can't be moved", status=404)
        return {"ok": True}

    @app.delete("/api/queue/{item_id}")
    def delete_queue_item(item_id: str):
        if not st.queue.remove(item_id):
            raise AppError("queue_item_not_found", "That item can't be removed (a running one must be cancelled first)", status=404)
        return {"ok": True}

    @app.post("/api/episodes/plan")
    def post_episodes_plan(body: dict | None = None):
        max_mb = float((body or {}).get("max_mb", 500))
        with st.lock:
            snap = copy.deepcopy(st.project)
        measured, samples, measure_error = (body or {}).get("measured_kbps"), [], None
        if measured is None and (body or {}).get("measure", True):
            # encode a few short samples of this footage: the real size is far below the worst-case cap for easy footage
            q = copy.deepcopy(snap)
            q.export.quality = capped_quality(q.export.quality)
            sel = q.selection or Selection(0.0, edited_duration(q.clips))
            m = measure(q, sel.start, sel.end)
            measured, samples, measure_error = m.kbps, m.samples, m.error
        eps, n_intros = episode_plan(snap, max_mb, measured)
        intros = [{"id": c.id, "name": os.path.basename(c.path)} for c in snap.clips if c.role == "intro"]
        return {"episodes": [episode_json(e) for e in eps], "intro_clips": n_intros, "intros": intros,
                "intro_reused": n_intros > 0 and n_intros < len(eps), "measured_kbps": measured,
                "samples": samples, "measure_error": measure_error}

    @app.post("/api/episodes/export")
    def post_episodes_export(body: dict | None = None):
        max_mb = float((body or {}).get("max_mb", 500))
        with st.lock:
            snap = copy.deepcopy(st.project)
        eps = prepare_episodes(snap, max_mb, (body or {}).get("intro_ids"), (body or {}).get("measured_kbps"))
        return {"job": st.jobs.submit(lambda progress, cancel: run_episode_set(snap, eps, max_mb, progress, cancel), "export")}

    def set_export_folder(path: str) -> dict:
        path = path.strip().strip('"')
        if path:
            try:
                os.makedirs(path, exist_ok=True)
                probe = tempfile.NamedTemporaryFile(dir=path, prefix=".vidcut_", delete=True)
                probe.close()
            except OSError as e:
                raise AppError("folder_unwritable", "Can't write to this folder",
                               "Choose another folder or check its write permissions", str(e)) from e
        with st.lock:
            st.project.export.out_dir = path
            st.save()
        return {"out_dir": path}

    @app.post("/api/export-folder")
    def post_export_folder(body: dict):
        return set_export_folder(str(body.get("path", "")))

    @app.post("/api/export-folder/pick")
    def pick_export_folder():
        path = _pick_folder()
        return set_export_folder(path) if path else {"out_dir": st.project.export.out_dir}

    @app.post("/api/export/estimate")
    def post_export_estimate():
        """Length and expected size of the file an export would produce, from the saved project."""
        with st.lock:
            snap = copy.deepcopy(st.project)
        try:
            seconds = export_duration(snap)
        except ValueError as e:  # "selection_invalid" -> the Thai message
            raise from_exception(e) from e
        s = _normalized(snap.export)
        src = source_video_kbps(snap.clips)
        return {"seconds": seconds, "bytes": estimate_bytes(s, snap.preset, seconds, src),
                "video_kbps": video_kbps(s, snap.preset, seconds, src), "audio_kbps": AUDIO_KBPS[s.container],
                "source_kbps": round(src) if src else None,
                "upper_bound": s.quality in CONSTANT_QUALITY}

    @app.post("/api/export/measure")
    def post_export_measure(body: dict | None = None):
        """Encode a few short samples of the real footage at the chosen settings and say how big the whole file will be:
        the estimate for constant-quality modes is only an upper bound (the cap), the footage usually lands far below it."""
        with st.lock:
            snap = copy.deepcopy(st.project)
        if not snap.clips:
            raise AppError("no_clips", "No clips in the project", "Add a clip first")
        try:
            seconds = export_duration(snap)
        except ValueError as e:
            raise from_exception(e) from e
        sel = snap.selection or Selection(0.0, edited_duration(snap.clips))
        audio = AUDIO_KBPS[_normalized(snap.export).container]

        def work(progress, cancel):
            m = measure(snap, sel.start, sel.end, cancel, progress)
            if m.kbps is None:
                raise AppError("measure_failed", "Couldn't measure the real size", m.error or "")
            mean = m.kbps / SAFETY
            return {"bytes": round((mean + audio) * 1000 / 8 * seconds * CONTAINER_OVERHEAD), "kbps": round(mean),
                    "samples": m.samples, "seconds": seconds}
        return {"job": st.jobs.submit(work, "measure")}

    @app.post("/api/preview-frame")
    def post_preview_frame(body: dict):
        """Render one real frame through the export pipeline, so framing/subtitles can be checked."""
        with st.lock:
            snap = copy.deepcopy(st.project)
        if not snap.clips:
            raise AppError("no_clips", "No clips in the project", "Add a clip first")
        work_dir = tempfile.mkdtemp(prefix="vidcut_pf_")
        out = os.path.join(work_dir, "frame.png")
        try:
            render_preview_frame(snap, float(body.get("t", 0)), out)
        except Exception:
            shutil.rmtree(work_dir, ignore_errors=True)
            raise
        return FileResponse(out, media_type="image/png", background=BackgroundTask(shutil.rmtree, work_dir, True))

    @app.get("/exports/{name}")
    def get_export(name: str):
        path = os.path.join(st.exports, name)
        if name != os.path.basename(name) or not os.path.isfile(path):
            raise AppError("file_missing", "Exported file not found", status=404)
        return FileResponse(path, filename=name)

    # ---- jobs / housekeeping -------------------------------------------------------------
    @app.get("/api/jobs/{job_id}")
    def get_job(job_id: str):
        job = st.jobs.get(job_id)
        if job is None:
            raise AppError("job_not_found", "Job not found", status=404)
        return job

    @app.get("/api/jobs/{job_id}/events")
    def job_events(job_id: str):
        if st.jobs.get(job_id) is None:
            raise AppError("job_not_found", "Job not found", status=404)

        def gen():
            for snap in st.jobs.events(job_id):
                yield f"data: {json.dumps(snap, ensure_ascii=False)}\n\n"
        return StreamingResponse(gen(), media_type="text/event-stream")

    @app.post("/api/jobs/{job_id}/cancel")
    def cancel_job(job_id: str):
        if not st.jobs.cancel(job_id):
            raise AppError("job_not_found", "Job not found", status=404)
        return {"ok": True}

    @app.post("/api/clear-temp")
    def clear_temp():
        if st.jobs.active():  # running jobs are using proxies and vidcut_* work dirs
            raise AppError("busy", "A job is running", "Wait for the job to finish, then clear temp files", status=409)
        freed = skipped = 0
        with st.lock:
            keep = {os.path.abspath(c.proxy_path) for c in st.project.clips if c.proxy_path}
        if os.path.isdir(st.proxies):
            for f in os.listdir(st.proxies):
                p = os.path.abspath(os.path.join(st.proxies, f))
                if p in keep:
                    continue
                try:
                    size = os.path.getsize(p)
                    os.remove(p)
                    freed += size
                except OSError:  # e.g. still open in a player on Windows
                    skipped += 1
        tmp = tempfile.gettempdir()
        for d in os.listdir(tmp):
            if d.startswith(TEMP_PREFIXES) and os.path.isdir(os.path.join(tmp, d)):
                shutil.rmtree(os.path.join(tmp, d), ignore_errors=True)
        return {"freed_bytes": freed, "skipped": skipped}

    if BRAND_LOGOS_DIR.is_dir():
        app.mount("/brand-logos", StaticFiles(directory=str(BRAND_LOGOS_DIR)), name="brand-logos")
    if FONTS_DIR.is_dir():  # bundled Thai fonts, so the browser preview matches the export
        app.mount("/fonts", StaticFiles(directory=str(FONTS_DIR)), name="fonts")
    if WEB_DIR.is_dir():
        app.mount("/", FreshStaticFiles(directory=str(WEB_DIR), html=True), name="web")
    return app


def run_server(port: int = 8765) -> None:
    uvicorn.run(create_app(), host=HOST, port=port, log_level="warning")


if __name__ == "__main__":
    port = int(os.environ.get("VIDCUT_PORT", "8765"))
    if os.environ.get("VIDCUT_NO_BROWSER") != "1":
        threading.Timer(1.5, lambda: webbrowser.open(f"http://{HOST}:{port}")).start()
    run_server(port)
