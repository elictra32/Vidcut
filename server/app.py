"""FastAPI glue. Thin: every real decision lives in core/. Binds to 127.0.0.1 only."""
import copy
import json
import mimetypes
import os
import shutil
import tempfile
import threading
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
from core.export import render_preview_frame, run_export
from core.fonts import FONT_FILES
from core.media import FFmpegError, is_browser_playable, make_proxy, probe
from core.models import Clip, Keep, Project, Selection, project_from_dict, project_to_dict
from core.presets import PRESETS
from core.silence import detect_silences, keeps_from_silences
from core.waveform import waveform_peaks
from server import fake_whisper
from server.errors import AppError, from_exception, payload
from server.jobs import JobRunner
from server.project_store import default_home, load_project, save_project

HOST = "127.0.0.1"
ALLOWED_HOSTS = ("127.0.0.1", "localhost")  # Host/Origin we answer to: blocks DNS rebinding and cross-site POSTs
WEB_DIR = Path(__file__).resolve().parent.parent / "web"
FONTS_DIR = Path(__file__).resolve().parent.parent / "fonts"
TEMP_PREFIXES = ("vidcut_",)


class State:
    def __init__(self, home: str):
        self.home = home
        self.exports = os.path.join(home, "exports")
        self.proxies = os.path.join(home, "proxies")
        self.lock = threading.RLock()
        self.project = load_project(home)
        self.jobs = JobRunner()
        self.waveforms: dict = {}

    def save(self):
        with self.lock:
            save_project(self.project, self.home)

    def clip(self, clip_id: str) -> Clip:
        with self.lock:
            for c in self.project.clips:
                if c.id == clip_id:
                    return c
        raise AppError("clip_not_found", "ไม่พบคลิปนี้ในโปรเจกต์", status=404)


def _pick_file() -> str | None:
    override = os.environ.get("VIDCUT_PICK_OVERRIDE")
    if override:
        return override
    try:
        import tkinter
        from tkinter import filedialog
    except ImportError as e:
        raise AppError("picker_unavailable", "เปิดหน้าต่างเลือกไฟล์ไม่ได้",
                       "วางพาธของไฟล์วิดีโอในช่องแทน", status=501) from e
    root = tkinter.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    try:
        return filedialog.askopenfilename(
            title="เลือกวิดีโอ",
            filetypes=[("วิดีโอ", "*.mp4 *.mov *.mkv *.avi *.webm *.m4v"), ("ทุกไฟล์", "*.*")]) or None
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
                err = AppError("forbidden_origin", "คำขอนี้มาจากเว็บไซต์อื่น จึงถูกปฏิเสธ",
                               "ใช้ Vidcut ผ่านหน้าต่างที่เปิดจาก run.bat เท่านั้น", status=403)
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

    @app.put("/api/project")
    def put_project(body: dict):
        try:
            proj = project_from_dict(body)
            if proj.preset not in PRESETS:
                raise ValueError("preset")
        except (TypeError, KeyError, ValueError) as e:
            raise AppError("project_invalid", "ข้อมูลโปรเจกต์ไม่ถูกต้อง", "ลองรีเฟรชหน้าเว็บแล้วทำใหม่",
                           str(e), status=422) from e
        with st.lock:
            if proj.rev != st.project.rev:
                raise AppError("project_stale", "ข้อมูลในหน้านี้ไม่ใช่เวอร์ชันล่าสุด (มีงานเบื้องหลังเพิ่งทำเสร็จ)",
                               "โหลดข้อมูลล่าสุดให้แล้ว ลองแก้ไขอีกครั้ง", status=409)
            # The page owns keeps/framing/subtitles/style/selection. Everything about the media itself
            # (path, proxy, size, duration) is the server's, and clips only enter through /api/clips.
            current = {c.id: c for c in st.project.clips}
            clips = []
            for c in proj.clips:
                known = current.get(c.id)
                if known is not None:
                    known.keeps, known.framing = c.keeps, c.framing
                    clips.append(known)
            proj.clips = clips
            proj.subtitles = [s for s in proj.subtitles if s.clip_id in current]
            st.project = proj
            st.save()
            return {"ok": True, "rev": st.project.rev}

    # ---- clips ---------------------------------------------------------------------------
    def add_clip(path: str) -> dict:
        path = os.path.abspath(path)
        if not os.path.isfile(path):
            raise AppError("file_missing", "ไม่พบไฟล์นี้", "ตรวจว่าไฟล์ยังอยู่ในตำแหน่งเดิม", path, status=404)
        try:
            info = probe(path)
        except FFmpegError as e:
            raise AppError("unreadable_media", "ไฟล์วิดีโอนี้เสียหายหรืออ่านไม่ได้",
                           "ลองเปิดไฟล์ด้วยโปรแกรมเล่นวิดีโอก่อน หรือแปลงไฟล์ใหม่", e.details) from e
        clip = Clip(id=uuid.uuid4().hex[:8], path=path, duration=info["duration"], width=info["width"],
                    height=info["height"], fps=info["fps"], has_audio=info["has_audio"],
                    keeps=[Keep(0.0, info["duration"])])
        with st.lock:
            st.project.clips.append(clip)
            st.project.rev += 1
            st.save()
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
                st.project.rev += 1
                st.save()
            return {"keeps": [asdict(k) for k in keeps]}
        return {"job": st.jobs.submit(work, "silence")}

    @app.get("/api/clips/{clip_id}/waveform")
    def get_waveform(clip_id: str, points: int = 2000):
        clip = st.clip(clip_id)
        key = (clip_id, points)
        if key not in st.waveforms:
            st.waveforms[key] = waveform_peaks(clip.path, points)
        return {"peaks": st.waveforms[key]}

    @app.get("/media/{clip_id}")
    def get_media(clip_id: str):
        clip = st.clip(clip_id)
        path = clip.proxy_path if clip.proxy_path and os.path.exists(clip.proxy_path) else clip.path
        if not os.path.isfile(path):
            raise AppError("file_missing", "ไม่พบไฟล์ต้นฉบับ", "ตรวจว่าไฟล์ยังอยู่ในตำแหน่งเดิม", status=404)
        return FileResponse(path, media_type=mimetypes.guess_type(path)[0] or "video/mp4")

    # ---- transcribe / export -------------------------------------------------------------
    @app.post("/api/transcribe")
    def post_transcribe(body: dict | None = None):
        model = (body or {}).get("model", "large-v3")
        with st.lock:
            snap = copy.deepcopy(st.project)
        if snap.selection is None:
            raise AppError("no_selection", "ยังไม่ได้เลือกช่วงที่จะถอดเสียง",
                           "ตั้งจุดเริ่ม/จบ (In/Out) บน timeline ก่อน")
        factory = fake_whisper.factory if os.environ.get("VIDCUT_FAKE_WHISPER") == "1" else None

        def work(progress, cancel):
            progress(0.0, "กำลังเตรียมเสียงและโหลดโมเดล (ครั้งแรกต้องดาวน์โหลด)")
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
            raise AppError("preset_unknown", "ไม่รู้จัก preset นี้")
        with st.lock:
            if preset:
                st.project.preset = preset
                st.save()
            snap = copy.deepcopy(st.project)

        def work(progress, cancel):
            res = run_export(snap, st.exports, progress, cancel)
            return {"mp4": os.path.basename(res.mp4), "srt": os.path.basename(res.srt), "dir": st.exports}
        return {"job": st.jobs.submit(work, "export")}

    @app.post("/api/preview-frame")
    def post_preview_frame(body: dict):
        """Render one real frame through the export pipeline, so framing/subtitles can be checked."""
        with st.lock:
            snap = copy.deepcopy(st.project)
        if not snap.clips:
            raise AppError("no_clips", "ยังไม่มีคลิปในโปรเจกต์", "เพิ่มคลิปก่อน")
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
            raise AppError("file_missing", "ไม่พบไฟล์ที่ส่งออก", status=404)
        return FileResponse(path, filename=name)

    # ---- jobs / housekeeping -------------------------------------------------------------
    @app.get("/api/jobs/{job_id}")
    def get_job(job_id: str):
        job = st.jobs.get(job_id)
        if job is None:
            raise AppError("job_not_found", "ไม่พบงานนี้", status=404)
        return job

    @app.get("/api/jobs/{job_id}/events")
    def job_events(job_id: str):
        if st.jobs.get(job_id) is None:
            raise AppError("job_not_found", "ไม่พบงานนี้", status=404)

        def gen():
            for snap in st.jobs.events(job_id):
                yield f"data: {json.dumps(snap, ensure_ascii=False)}\n\n"
        return StreamingResponse(gen(), media_type="text/event-stream")

    @app.post("/api/jobs/{job_id}/cancel")
    def cancel_job(job_id: str):
        if not st.jobs.cancel(job_id):
            raise AppError("job_not_found", "ไม่พบงานนี้", status=404)
        return {"ok": True}

    @app.post("/api/clear-temp")
    def clear_temp():
        if st.jobs.active():  # running jobs are using proxies and vidcut_* work dirs
            raise AppError("busy", "มีงานกำลังทำงานอยู่", "รอให้งานเสร็จก่อน แล้วค่อยล้างไฟล์ชั่วคราว", status=409)
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

    if FONTS_DIR.is_dir():  # bundled Thai fonts, so the browser preview matches the export
        app.mount("/fonts", StaticFiles(directory=str(FONTS_DIR)), name="fonts")
    if WEB_DIR.is_dir():
        app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="web")
    return app


def run_server(port: int = 8765) -> None:
    uvicorn.run(create_app(), host=HOST, port=port, log_level="warning")


if __name__ == "__main__":
    port = int(os.environ.get("VIDCUT_PORT", "8765"))
    if os.environ.get("VIDCUT_NO_BROWSER") != "1":
        threading.Timer(1.5, lambda: webbrowser.open(f"http://{HOST}:{port}")).start()
    run_server(port)
