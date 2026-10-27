# THUS short-form style: measured from Ep3 (57.45 s) and Ep4 (99.46 s)

Every number below was measured from the pixels/samples of the two reference clips (`scripts/measure.py`, 21 checks, both clips pass 100%).
"ไม่แน่ใจ" marks what could not be told. Targets for automatic checks are in `style.json`.

## 1. Basic info
| | Ep3 | Ep4 |
|---|---|---|
| size / aspect | 1080x1920, 9:16 | same |
| frame rate | 25 fps | 25 fps |
| duration | 57.45 s | 99.46 s |
| video | H.264, yuv420p, 2,462 kbps | 2,178 kbps |
| audio | AAC, 48 kHz stereo, 237 kbps | 239 kbps |
| container | mp4 | mp4 |

## 2. Cut pacing
| | Ep3 | Ep4 |
|---|---|---|
| cuts (incl. the one into the end card) | 11 | 8 |
| cuts per minute | 11.5 | 4.8 |
| shot length mean / median | 4.92 / 3.44 s | 12.07 / 11.82 s |
| shots, in order (s) | 15.52, 4.80, 2.48, **0.12**, 7.36, 2.56, 3.40, 9.24, 3.44, **0.20**, 5.04 (+ card 3.28) | 7.52, 4.76, 4.12, 14.56, 9.08, 22.24, 16.68, 17.56 (+ card 2.92) |

- Opening: no cut in the first 3 s. The first shot is the stacked split-screen and lasts 15.52 s / 7.52 s; the first cut is at 15.52 s / 7.52 s.
- Two reaction flashes in Ep3 only: 3 frames (0.12 s) and 5 frames (0.20 s). Not sure they are intentional.
- Dead air: pauses of 0.3 s or more inside speech: Ep3 4 (longest 0.32 s), Ep4 15 (longest 0.82 s). Speech pauses are cut tight; nothing above 0.9 s.
- Word-level cut timing was not measured (no Whisper model available offline).

## 3. Text and subtitles
- **No running subtitles.** Checked every 1 s (Ep3 lower 36% of the frame) and every 2 s (Ep4); only the hook title exists.
- Hook title: appears at t = 0.00 s (no fade-in, no animation), 2-3 stacked lines, white, centred.
  - Ep3: "วันที่ตลาด" / "ตบหน้า". Ep4: "จิตใจ" / "หลังจากหายไป" / "40 ล้าน".
  - Ink block centre x = 532 / 538, y = 935 / 940 (frame centre is 540 / 960). It straddles the split seam at y ≈ 963.
  - Each full line is scaled so its ink is 832-846 px wide (77-78% of the frame). Ep3 fitted sizes (px em) 200 and 287; Ep4 139 and 253.
    A short line that would become taller than ~240 px takes its neighbour's size (Ep4 "จิตใจ" = 136, same as the line after it).
  - Ink height of a normal line 110-114 px (+ tone marks), big last line 218-231 px; gap between line ink boxes 19-77 px (mean about 42).
  - Fully opaque (alpha 1.00, RGB 255,255,255) until 4.04 s, then a **linear fade-out of 1.0 s**, gone at 5.04 s (per-frame alpha, both clips identical).
- Font: Prompt family (ink-box aspect of "ตบหน้า" 3.62 vs Prompt 3.65, Sarabun 2.99). Ink density 0.353 vs Prompt Medium 0.332: the weight is a step above Medium (SemiBold?), not sure.
  Only Light/Regular/Medium are shipped in `fonts/`, so Medium + 1.5 px same-colour outline is used.
- End card text: "รับชมคลิปเต็มได้ที่" / YouTube icon + "THUS House" / THUS lock-up, white, centred at (536, 940); lines at y 815-857, 883-940, 969-1065.

## 4. Colour and identity
- End card background **#271136** (39,17,54), text **#FFFFFF**. The two end cards differ by 0.08/255 on average (same card).
- Title and watermark: **#FFFFFF**, no shadow or outline measured.
- Footage palette (not brand colours, from the set): wall grey #AAAAA6, jacket brown #8B5947 / #6B5049, dark #382726, beige #AEA492. No colour grade measured.
- Watermark: THUS "HOUSE OF TRADERS" lock-up, white, top right: x 818-1024 (207 px wide, 19% of the width), y 91-169, margins 55 px right and 91 px top.
  Present in every shot from the first frame to the last frame before the end card, absent on the end card. No box or band.

## 5. Transitions
- 19 of 19 cuts are hard cuts: one frame jumps (mean difference 54-95), the frames on both sides are calm (0.2-4.3).
- Entry into the end card is a hard cut (difference 95). No fade in at the start or fade to black at the end.

## 6. Motion and zoom
- None. Camera framing is locked inside every shot: vertical drift 0 px in 13 of 14 measured shots, 10 px (one measuring step) in one; no punch-in, pan or shake.
- Variety comes only from the shot type: split-screen (top camera: woman, bottom camera: man, seam at y ≈ 963) vs a single-camera close-up.
  Close-up scale vs the split framing: about 2-2.5x (estimated from head width, ไม่แน่ใจ).

## 7. Animation and graphics
- Only the title fade-out. No icons, stickers, emoji, B-roll or lower thirds. Watermark and end card are static.

## 8. Audio
| | Ep3 | Ep4 |
|---|---|---|
| integrated loudness | -15.3 LUFS | -16.9 LUFS |
| loudness range | 5.6 LU | 6.4 LU |
| true peak | -0.4 dBFS | -0.0 dBFS |

- Target used for new shorts: -16 LUFS (two-pass loudnorm, true peak limit -1.5 dBFS).
- End card is digital silence (-91 dB) for 3.28 s / 2.92 s.
- No music bed found: speech pauses fall below -45 dB. Sound effects on cuts were not measured.

## 9. Techniques that make it look the way it does
1. Open on both speakers stacked, so the viewer sees the conversation and the reaction at once, with the hook title laid across the seam.
2. Fit each title line to the same width so the key line (a number or a word) is the biggest thing on screen.
3. Cut to a tight single-camera shot on whoever carries the story, back to the stacked shot for reactions; locked framing, hard cuts only.
4. Constant watermark, silent branded CTA card of about 3 s to finish.
5. Pauses trimmed so the longest gap inside speech stays under 0.9 s.

## 10. Result of the measurement
Both reference clips pass all 21 checks in `style.json` (100%), as they must; the real test is on a new render (`test-report.md`).
