"""Colour correction per clip (warmth, tint, brightness, contrast, saturation), shared by the export (ffmpeg filters)
and the preview (web/grade.js builds the same numbers into an SVG colour matrix, kept in step by tests/fixtures/grade_cases.json)."""
from core.models import Grade

LIMIT = 100.0


def clamp(g: Grade) -> Grade:
    f = lambda v: max(-LIMIT, min(LIMIT, float(v or 0.0)))
    return Grade(f(g.temperature), f(g.tint), f(g.brightness), f(g.contrast), f(g.saturation))


def is_neutral(g: Grade) -> bool:
    return all(abs(v) < 1e-9 for v in (g.temperature, g.tint, g.brightness, g.contrast, g.saturation))


def grade_params(g: Grade) -> dict:
    """Channel gains and the eq() values for a grade."""
    g = clamp(g)
    return {"r": 1 + 0.30 * g.temperature / LIMIT, "g": 1 - 0.25 * g.tint / LIMIT, "b": 1 - 0.30 * g.temperature / LIMIT,
            "brightness": 0.25 * g.brightness / LIMIT, "contrast": 1 + 0.5 * g.contrast / LIMIT, "saturation": 1 + g.saturation / LIMIT}


def _n(x: float) -> str:
    return f"{x:.4f}".rstrip("0").rstrip(".") or "0"


def grade_filter(g: Grade, matrix: str = "bt709") -> str:
    """ffmpeg filter text for the grade, '' when it changes nothing. `matrix` is the YUV<->RGB conversion the picture was
    made with (bt709 for HD, bt601 for SD: what a player assumes for an untagged file). Warmth/tint work in RGB, so the
    picture is converted with exactly that matrix and back; letting ffmpeg pick would shift every colour a little."""
    if is_neutral(g):
        return ""
    p = grade_params(g)
    parts = []
    if any(abs(p[k] - 1) > 1e-9 for k in ("r", "g", "b")):
        parts.append(f"scale=in_color_matrix={matrix}:in_range=tv,format=gbrp,"
                     f"colorchannelmixer=rr={_n(p['r'])}:gg={_n(p['g'])}:bb={_n(p['b'])},"
                     f"scale=out_color_matrix={matrix}:out_range=tv,format=yuv420p")
    if abs(p["brightness"]) > 1e-9 or abs(p["contrast"] - 1) > 1e-9 or abs(p["saturation"] - 1) > 1e-9:
        parts.append(f"eq=brightness={_n(p['brightness'])}:contrast={_n(p['contrast'])}:saturation={_n(p['saturation'])}")
    return ",".join(parts)
