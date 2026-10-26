"""The fonts shipped in fonts/, and how their sizes map between CSS and ASS.

CSS font-size is the em size. libass Fontsize is the font's full line height, taken from the OS/2
usWinAscent + usWinDescent (VSFilter compatibility). For Thai fonts with tall metrics (Sarabun: 1.85 em)
the same number therefore renders about half as large in the export as in the browser preview.
`ass_size_factor` converts: ASS Fontsize = CSS size * factor."""
import struct
from functools import lru_cache
from pathlib import Path

FONTS_DIR = Path(__file__).resolve().parent.parent / "fonts"

# family name used in the UI, the project and ASS -> file in fonts/
FONT_FILES = {
    "Sarabun": "Sarabun-Regular.ttf",
    "Prompt": "Prompt-Regular.ttf",
    "Prompt Medium": "Prompt-Medium.ttf",
}


@lru_cache(maxsize=None)
def ass_size_factor(family: str) -> float:
    file = FONT_FILES.get(family)
    if not file:
        return 1.0  # a system font we can't inspect: assume ASS and CSS sizes agree
    data = (FONTS_DIR / file).read_bytes()
    count = struct.unpack(">H", data[4:6])[0]
    tables = {}
    for i in range(count):
        tag, _, offset, _length = struct.unpack(">4sIII", data[12 + 16 * i: 28 + 16 * i])
        tables[tag] = offset
    upem = struct.unpack(">H", data[tables[b"head"] + 18: tables[b"head"] + 20])[0]
    win_ascent, win_descent = struct.unpack(">HH", data[tables[b"OS/2"] + 74: tables[b"OS/2"] + 78])
    return (win_ascent + win_descent) / upem
