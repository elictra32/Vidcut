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
        return AppError("no_audio", "ไม่พบเสียงในคลิปนี้", "เลือกช่วงที่มีเสียงพูด หรือข้ามขั้นตอนถอดเสียงแล้วพิมพ์ซับเอง")
    if isinstance(e, ExportError):
        return AppError(e.code, e.message_th, "", e.details or None)
    if isinstance(e, ValueError) and str(e) == "selection_invalid":
        return AppError("selection_invalid", "ช่วงที่เลือกไม่ถูกต้อง",
                        "ตั้งจุดเริ่ม/จบใหม่ และเปิดช่วงที่ถูกตัดอย่างน้อยหนึ่งช่วง")
    if isinstance(e, FFmpegError):
        return AppError("ffmpeg_failed", "ffmpeg ทำงานไม่สำเร็จ", "ตรวจว่าไฟล์วิดีโอยังอยู่และเปิดได้ปกติ",
                        getattr(e, "details", None), status=500)
    if isinstance(e, FileNotFoundError):
        if "ffmpeg" in str(e).lower():
            return AppError("ffmpeg_missing", "ไม่พบ ffmpeg", "รัน setup.bat อีกครั้งเพื่อติดตั้ง ffmpeg", status=503)
        return AppError("file_missing", "ไม่พบไฟล์", "ตรวจว่าไฟล์ยังอยู่ในตำแหน่งเดิม", status=404)
    return AppError("internal", "เกิดข้อผิดพลาดที่ไม่คาดคิด", "ลองอีกครั้ง ถ้ายังเป็นอยู่ให้ดูรายละเอียดด้านล่าง",
                    "".join(traceback.format_exception(e))[-3000:], status=500)
