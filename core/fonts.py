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
    "Prompt Light": "Prompt-Light.ttf",  # the THUS brand Thai typeface (named in its logo manual)
    "Prompt Medium": "Prompt-Medium.ttf",
    "Montserrat": "Montserrat-Regular.ttf",  # the THUS brand typeface (official static Regular/Medium from Google Fonts)
    "Montserrat Medium": "Montserrat-Medium.ttf",
    # more looks for covers and subtitles (all SIL OFL, from Google Fonts); each draws Thai and Latin
    "Kanit Medium": "Kanit-Medium.ttf",              # modern, rounded-square: good for big titles
    "Kanit Light": "Kanit-Light.ttf",
    "Mitr Medium": "Mitr-Medium.ttf",                # friendly, heavy rounded
    "Bai Jamjuree Medium": "BaiJamjuree-Medium.ttf", # clean, a little techy
    "Chakra Petch Medium": "ChakraPetch-Medium.ttf", # angular, trading / tech feel
    "IBM Plex Sans Thai Medium": "IBMPlexSansThai-Medium.ttf",  # neutral and very readable
    "Pridi Medium": "Pridi-Medium.ttf",              # serif, elegant
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


@lru_cache(maxsize=None)
def _glyph_widths(file: str):
    """(unitsPerEm, cmap {codepoint: glyph id}, advances [per glyph]) read straight from a TrueType file."""
    data = (FONTS_DIR / file).read_bytes()
    count = struct.unpack(">H", data[4:6])[0]
    tables = {}
    for i in range(count):
        tag, _, offset, length = struct.unpack(">4sIII", data[12 + 16 * i: 28 + 16 * i])
        tables[tag] = (offset, length)
    upem = struct.unpack(">H", data[tables[b"head"][0] + 18: tables[b"head"][0] + 20])[0]
    n_metrics = struct.unpack(">H", data[tables[b"hhea"][0] + 34: tables[b"hhea"][0] + 36])[0]
    hm = tables[b"hmtx"][0]
    advances = [struct.unpack(">H", data[hm + 4 * i: hm + 4 * i + 2])[0] for i in range(n_metrics)]
    cm = tables[b"cmap"][0]
    n_sub = struct.unpack(">H", data[cm + 2: cm + 4])[0]
    cmap: dict[int, int] = {}
    for i in range(n_sub):
        plat, enc, off = struct.unpack(">HHI", data[cm + 4 + 8 * i: cm + 12 + 8 * i])
        if (plat, enc) not in ((3, 1), (3, 10), (0, 3), (0, 4)):
            continue
        sub = cm + off
        fmt = struct.unpack(">H", data[sub: sub + 2])[0]
        if fmt == 4:
            segx2 = struct.unpack(">H", data[sub + 6: sub + 8])[0]
            seg = segx2 // 2
            ends = struct.unpack(f">{seg}H", data[sub + 14: sub + 14 + segx2])
            starts = struct.unpack(f">{seg}H", data[sub + 16 + segx2: sub + 16 + 2 * segx2])
            deltas = struct.unpack(f">{seg}h", data[sub + 16 + 2 * segx2: sub + 16 + 3 * segx2])
            ro_pos = sub + 16 + 3 * segx2
            offs = struct.unpack(f">{seg}H", data[ro_pos: ro_pos + segx2])
            for s in range(seg):
                for c in range(starts[s], ends[s] + 1):
                    if c == 0xFFFF:
                        continue
                    if offs[s] == 0:
                        g = (c + deltas[s]) & 0xFFFF
                    else:
                        p = ro_pos + 2 * s + offs[s] + 2 * (c - starts[s])
                        g = struct.unpack(">H", data[p: p + 2])[0]
                        g = (g + deltas[s]) & 0xFFFF if g else 0
                    if g:
                        cmap.setdefault(c, g)
        elif fmt == 12:
            n_groups = struct.unpack(">I", data[sub + 12: sub + 16])[0]
            for g_i in range(n_groups):
                a, b, gid = struct.unpack(">III", data[sub + 16 + 12 * g_i: sub + 28 + 12 * g_i])
                for c in range(a, b + 1):
                    cmap.setdefault(c, gid + c - a)
    return upem, cmap, advances


def text_advance(family: str, text: str, px: float, spacing: float = 0.0) -> float:
    """Width in pixels of `text` set in a bundled font at em size `px`, plus `spacing` after every character.
    Ignores kerning, so it is within about 1-2% for Latin text."""
    file = FONT_FILES[family]
    upem, cmap, advances = _glyph_widths(file)
    total = 0.0
    for ch in text:
        gid = cmap.get(ord(ch), 0)
        total += advances[min(gid, len(advances) - 1)] * px / upem + spacing
    return total
