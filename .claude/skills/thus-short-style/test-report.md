# Test report

Rendered with `scripts/build_short.py` from **synthetic** cameras (flat colour + moving box + sine tone), not real footage:
5 shots (split, 3 close-ups incl. a 0.12 s flash, split) + title + watermark + end card, then measured back with `scripts/measure.py --check`.

- Cuts land on the edit list: 0.0, 6.4, 9.2, 9.32, 11.2 and the end card at 13.0 s; 0 soft cuts.
- 20 of 20 checks in `style.json` pass (100%): 1080x1920 at 25 fps, title ink 832 px wide centred at (534, 937), fully opaque until 4.08 s and gone at 5.0 s,
  watermark 207 px wide with margins 55/92 px, end card 3.1 s and silent (-91 dB), loudness -16.0 LUFS.
- Reference clips Ep3 and Ep4 themselves score 100% (they set the targets).
- Not covered: real faces (crop position `cx` / `cu_zoom` need a look on real footage), real speech loudness peaks, video bitrate
  (flat synthetic video compresses to ~75 kbps; the encoder is set to 2,400 kbps target / 2,800 kbps max for real footage), and Thai subtitles (the style has none).
- Automated: `pytest tests/test_thus_style.py` (needs ffmpeg with libass).
