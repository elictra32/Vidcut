---
name: thus-short-style
description: Use when the user wants to cut a THUS House podcast clip into a 9:16 short in the house style (stacked two-speaker split-screen opening with a big hook title, hard cuts to close-ups, THUS watermark, purple end card, -16 LUFS), or asks to check a short against that style. Style measured from the reference shorts Ep3 and Ep4.
---

# thus-short-style

Builds and checks 1080x1920, 25 fps shorts that match the measured house style (`style-guide.md`, targets in `style.json`).
Work on copies. Never overwrite the user's camera files. Report measured numbers (seconds, px, percent, HEX), never "fast"/"big".
If something cannot be told (a font weight, why a cut is where it is) write "ไม่แน่ใจ" and say so. Copy style and technique only,
never the footage, music or voices of a reference clip.

## Needs
ffmpeg + ffprobe with libass, Python 3.9+, numpy. Fonts: `Prompt-Medium.ttf` (the repo's `fonts/` folder is found automatically; else `--fonts DIR`).
Assets (already in `assets/`): `endcard.png` (the purple CTA card), `watermark.png` (THUS lock-up, 207 px wide, transparent).
They were cut from the owner's own clips with `scripts/extract_assets.py ref/ep3.mp4`.

## Steps
1. **Probe the inputs**: `ffprobe` both camera files (top = guest/woman side, bottom = host/man side). They must be synced; say the sizes, fps and duration back.
2. **Decide the shots** (ask the user for the hook text and which spans to keep; do not invent dialogue). Rules from the references:
   - first shot is `split` (both cameras stacked, top camera above) and carries the hook title; it lasts 7.5-15.5 s in the references
   - then `cu` (close-up, one camera, 9:16 crop) on whoever carries the story, back to `split` for reactions
   - all cuts are hard cuts; no dissolves, no zooms, no pans; framing stays locked inside a shot
   - roughly 5-12 cuts per minute; mean shot 5-12 s; trim speech pauses to at most ~0.9 s (references: longest 0.32 s and 0.82 s)
3. **Write `edl.json`** (copy `examples/edl.example.json`): `cams`, `audio` (which camera supplies the sound), `title.lines` (2-3 short lines, key word/number on the last line), `shots`.
4. **Dry-check the numbers**, then render:
   `python .claude/skills/thus-short-style/scripts/build_short.py edl.json -o short.mp4`
   It lays the title out itself (each line scaled so its ink is about 835 px wide, stacked, centred at 534,938, Prompt Medium, white),
   keeps it fully opaque for 4.04 s then fades it out linearly over 1.0 s, puts the watermark on the video part (not on the end card),
   appends the 3.1 s end card with digital silence, and sets loudness to -16 LUFS (two-pass).
5. **Verify**: `python .claude/skills/thus-short-style/scripts/measure.py short.mp4 --check` and report the `match: NN%` line plus every FAIL.
   Then look at three frames (title frame, a close-up, the end card) before saying it is done.
6. **Tune**: user feedback as numbers ("title 20% smaller" -> change `TITLE_INK_W` in `build_short.py`; edit `style.json` ranges only if the user changes the style on purpose).

## Limits (say them)
- Whisper was not available when the style was measured, so subtitle/word timing was not measured; the references have no running subtitles. If the user wants subtitles, that is a new decision, not part of this style.
- `Prompt Medium` is the closest shipped weight; the reference title looks one step bolder (SemiBold?). `OUTLINE` in `build_short.py` thickens it slightly. Not sure of the exact weight.
- The close-up zoom relative to the split framing was estimated by eye at about 2-2.5x; check the crop on real footage and adjust `cu_zoom` / `cx`.

## Text-only short (no footage)
`python .claude/skills/thus-short-style/scripts/text_short.py scenes.json -o out.mp4` turns a scene list (2-3 short lines + seconds each) into a silent
1080x1920 short with the same title rules (fitted lines, white Prompt Medium, hard cuts). Example: `examples/best_loser_wins_60s.json`
(60 s from the Best Loser Wins podcast script). No voice is generated; scene lengths are a reading pace, not tied to audio.

## B-roll (from Media Finder)
- `{"layout": "broll", "file": "x.mp4|x.gif|x.png", "t0": 2.0, "t1": 5.0}` in `edl.json` shows the file full-frame (cropped to fill, looped if shorter, `from` = start offset in a video)
  while the main audio keeps playing. The measured THUS style has **no B-roll**, so use it only when the user asks for it; hard cuts in and out, no zoom.
- `scripts/cue_to_edl.py cue-sheet.md --as shots` turns a Media Finder cue sheet into broll shots; `--as scenes` into text_short scenes with `media` backgrounds.
  `--skip-gif` when the video may become a paid ad (Tenor GIFs are organic-only). Find the media itself with the `media-finder` skill on the user's machine
  (this cloud sandbox cannot reach Pexels/Tenor/Iconify).
