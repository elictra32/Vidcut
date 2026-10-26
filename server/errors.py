"""User-facing errors: Thai message + suggested fix, with technical details in a fold-out."""
import traceback

from core.export import ExportError
from core.media import FFmpegError, NoAudioError


class AppError(Exception):
    def __init__(self, code: str, message: str, hint: str = "", details=None, status: int = 400):
        super().__init__(message)
        self.code, self.message, self.hint, self.details, self.status = code, message, hint, details, status


def payload(e: AppError) -> dict:
    return {"code": e.code, "message": e.message, "hint": e.hint, "details": e.details}


def from_exception(e: Exception) -> AppError:
    if isinstance(e, AppError):
        return e
    if isinstance(e, NoAudioError):
        return AppError("no_audio", "No audio in this clip", "Pick a range with speech, or skip transcription and type the subtitles yourself")
    if isinstance(e, ExportError):
        return AppError(e.code, e.message_th, "", e.details or None)
    if isinstance(e, ValueError) and str(e) == "selection_invalid":
        return AppError("selection_invalid", "The selection is invalid",
                        "Set start/end again and re-enable at least one cut section")
    if isinstance(e, FFmpegError):
        return AppError("ffmpeg_failed", "ffmpeg failed", "Check that the video file still exists and opens normally",
                        getattr(e, "details", None), status=500)
    if isinstance(e, FileNotFoundError):
        if "ffmpeg" in str(e).lower():
            return AppError("ffmpeg_missing", "ffmpeg not found", "Run setup.bat again to install ffmpeg", status=503)
        return AppError("file_missing", "File not found", "Check that the file is still in its original location", status=404)
    return AppError("internal", "An unexpected error occurred", "Try again. If it keeps happening, see the details below",
                    "".join(traceback.format_exception(e))[-3000:], status=500)
