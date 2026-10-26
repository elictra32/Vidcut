# Vidcut — Design Spec

Date: 2026-10-26
Status: Draft for user review

## 1. Goal

A local web app (run on the user's Windows 11 laptop) for cutting long Thai-language
videos down to short clips for TikTok and YouTube, with automatic Thai subtitles,
dead-air removal, and a subtitle editor. Core pipeline uses **no LLM and no paid API**,
so using it costs zero tokens.

### User & environment (from the user)

- Spoken language: Thai.
- Source clips: up to ~1 hour. Final output: usually 1–2 minutes. Long clips may only need dead-air removal.
- Hardware: AMD Ryzen 7 5700U (8 cores / 16 threads), 16 GB RAM, integrated Radeon (no CUDA), Windows 11, ~85 GB free disk. **CPU-only.**
- Targets: TikTok (9:16) and YouTube (16:9).
- Feature level: "medium" — multiple clips, auto subtitles, dead-air cut, timeline subtitle editing, styling, live preview, per-platform export.

### Success criteria

1. Add a 1-hour MP4, detect dead air, pick a 1–2 min range, auto-generate Thai subtitles for that range, edit them, export TikTok and YouTube MP4s with burned-in subtitles + `.srt`.
2. Subtitle lines never break mid-word in Thai.
3. Dead-air detection on a 1-hour clip finishes in minutes, not tens of minutes.
4. Transcribing a 2-minute range finishes in a few minutes on the target laptop (estimate 2–6 min; to be measured, not promised).
5. Source files are never modified.
6. Core logic (`core/`) is covered by automated tests that run without real video or a Whisper model.

## 2. Non-goals (v1)

- Effects, transitions, multiple video layers, audio mixing, keyframes.
- LLM features (typo correction, bad-take removal). Reserved for a later version; v1 does not include any LLM code.
- Cloud transcription, GPU acceleration, macOS/Linux packaging (code should not preclude them, but only Windows is supported and documented).
- Multi-user / network exposure. The server binds to `127.0.0.1` only.

## 3. Architecture

Python 3.11/3.12 backend (FastAPI + uvicorn) serving a static, build-less HTML/JS frontend. `ffmpeg` and `faster-whisper` do the heavy lifting.

```
vidcut/
  setup.bat / run.bat       install deps / launch server and open browser
  pyproject.toml            deps: fastapi, uvicorn, faster-whisper, pythainlp, pytest
  core/                     pure logic, no web code, unit-testable
    media.py                ffprobe wrapper, browser-playability check, proxy creation
    silence.py              dead-air detection -> keep segments
    timeline.py             clip/keep-segment/selection time mapping
    transcribe.py           faster-whisper wrapper
    thai_split.py           word segmentation + subtitle line building
    ass.py                  subtitle model -> ASS text, and -> SRT
    export.py               builds and runs the ffmpeg command per preset
    presets.py              TikTok / YouTube definitions
  server/
    app.py                  FastAPI routes
    jobs.py                 background job runner + progress events (SSE)
    project_store.py        load/save project.json
  web/
    index.html, app.js, ... player, timeline, subtitle editor, style panel (ES modules, no build)
  fonts/                    bundled open-source Thai fonts (e.g. Prompt, Sarabun)
  tests/
  README.md, ARCHITECTURE.md
```

Boundaries: `core/` never imports `server/` or `web/`. `server/` is thin glue. `web/` talks to `server/` over HTTP/JSON + SSE only.

### Local file access

Browsers cannot give the server a real path for a dropped file, and copying a 1-hour video is wasteful. The "Add clip" button therefore calls a server endpoint that opens a native Windows file picker (tkinter `filedialog`) and returns the chosen path. The project stores **paths**, not copies. The server serves media to the page via a ranged-GET endpoint keyed by clip id (not arbitrary paths).

## 4. Data model (`project.json`)

```
Project
  clips: [Clip]                      ordered
  selection: {in, out} | null        in project edited-time seconds
  subtitles: [Subtitle]              source-anchored; edited time is derived
  style: SubtitleStyle
  preset: "tiktok" | "youtube"
  framing: {mode: "crop"|"blur_fit", crop_center_x: 0..1}   per clip (stored on Clip)

Clip
  id, path, duration, width, height, fps, has_audio
  proxy_path | null                  null when the source is browser-playable
  keeps: [Keep]                      source-time segments that survive dead-air cut

Keep { start, end, enabled }         enabled=false means "this segment is cut"
  (dead-air gaps are the complement of enabled keeps)

Subtitle { id, clip_id, src_start, src_end, text, x, y }   source-anchored (see rule below); x,y optional per-line position override, 0..1 of frame
SubtitleStyle { font, size, color, outline_color, outline_width, shadow, bg_color|null, default_x, default_y, align }
```

### Time coordinates

- **Source time**: seconds in a clip's original file.
- **Edited time**: seconds along the concatenation of all *enabled* keeps of all clips, in clip order. Subtitles and selection live in edited time.
- `core/timeline.py` owns all conversions: `source_to_edited`, `edited_to_source_ranges(selection)` (returns the list of `(clip, src_start, src_end)` pieces covering a selection), and `shift` helpers. **Rule: a subtitle's source of truth is its source anchor** `(clip_id, src_start, src_end)`; edited-time values are always derived from it via `timeline.py`. Toggling a keep or re-running silence detection therefore never desyncs a subtitle from its speech. When the user drags a subtitle edge on the (edited-time) timeline, the new edited time is converted back to a source anchor. If an edge lands in a cut gap it is clamped to the nearest enabled keep boundary. A subtitle whose whole span falls inside cut gaps is hidden (kept in the project, not exported) and flagged in the list.

## 5. Workflow & module behavior

1. **Add clip.** `media.probe` (ffprobe) reads metadata. If the container/codec is browser-playable (H.264 + AAC in MP4/WebM), the original is used for preview. Otherwise a 480p H.264 proxy is created in the background. Source is never modified.
2. **Dead-air detection.** Audio is decoded to 16 kHz mono and run through ffmpeg `silencedetect` (defaults: −35 dB, min 0.6 s, 0.15 s padding kept around speech; all three adjustable). Output is the list of keeps. The UI shows them on a waveform timeline; each can be toggled. Preview playback skips disabled segments (player seeks over cut gaps).
3. **Select range.** User sets In/Out in edited time (skipping this means "whole edited timeline", used for dead-air-only jobs).
4. **Transcribe the selection only.** Audio of the selection (via `edited_to_source_ranges`) is extracted and passed to faster-whisper: `language="th"`, `word_timestamps=True`, `vad_filter=True`, `compute_type="int8"`, `cpu_threads` = physical cores. Default model `large-v3`; selectable smaller models (`medium`, `small`) for speed. The model downloads on first use with a progress indicator. Results are streamed back as progress events.
5. **Thai segmentation & line building** (`thai_split.py`). Whisper's Thai "words" are sub-word tokens without spaces. Procedure: concatenate token text, distribute each token's time span across its characters, segment the full text with PyThaiNLP `newmm`, then derive each word's start/end from its characters. Lines are built greedily from words up to a per-preset max display width (Thai combining vowels/tone marks count as zero width), breaking only at word boundaries, and a line is also split at long pauses. Presets: TikTok ≈ short lines (1–2 lines on screen), YouTube ≈ longer lines.
6. **Edit.** Edit text, drag line edges on the timeline, drag a line's position on the preview, edit styles. Preview draws subtitles with HTML/CSS over the `<video>`.
7. **Export** (`export.py`). From the **original** file(s), only the selected pieces: ffmpeg `trim`/`atrim` + `concat` filter graph, then preset scaling/framing, then `subtitles=` (libass) with the generated ASS and the bundled `fonts/` dir. Output: `<name>_<preset>.mp4` (H.264, AAC) and `<name>_<preset>.srt`. ASS timestamps are shifted by the selection start. To avoid Windows path-escaping problems in the filter string, ffmpeg runs with its working directory set to a temp work dir containing the ASS file and a `fonts` link/copy, and references them by relative name.

### Presets

| | TikTok | YouTube |
|---|---|---|
| Frame | 1080×1920 | 1920×1080 |
| Subtitle default | larger font, lower-center, inside TikTok safe zone | smaller font, bottom-center |
| Max lines on screen | 2 | 2 |
| Source→frame | landscape source: `crop` (user-draggable center) or `blur_fit` (blurred copy as background); portrait source: scaled as is | scale/pad to 16:9 |

Preview shows safe-zone guides for the chosen preset.

## 6. Preview vs export fidelity

Preview subtitles are CSS; export subtitles are libass. They can differ slightly in font metrics and wrapping. Mitigation: a "Render preview frame" button runs the real export pipeline for one frame at the playhead and shows it, so the user can check exact output before a full export. The style → CSS and style → ASS mappings are defined once in `core/presets.py` / `ass.py` with shared constants.

## 7. Error handling

- All user-facing errors are Thai messages with a suggested fix (ffmpeg not found, unreadable/corrupt file, no audio track, model download failed, disk full, export failed with the last lines of ffmpeg stderr under a "details" fold-out).
- Background jobs are cancellable; cancelling kills the child process and removes partial output.
- Whisper hallucination on silence is reduced by `vad_filter`; empty transcription results show a clear "no speech found" state rather than an empty editor.
- `project.json` is written atomically (temp file + rename).
- A "Clear temp files" action removes proxies and temp work dirs.

## 8. Testing

- **Unit (pytest, no models, no real video):** `timeline.py` mapping (including toggled keeps, multi-clip, selection spanning cuts), `silence.py` against synthetic audio generated by ffmpeg (tone bursts + silence with known boundaries), `thai_split.py` (no mid-word breaks, width rules, pause splitting) with fixture token lists, `ass.py` (golden files) and SRT output, `export.py` command construction (golden argv).
- **Integration:** a small end-to-end export from a synthetic clip, asserting output duration and dimensions via ffprobe. A `slow`-marked test runs `faster-whisper` with a tiny model on a short synthetic/recorded clip; it is skipped by default.
- **UI smoke test:** Playwright (available in the build sandbox) loads the app against a synthetic clip and exercises add clip → detect → edit subtitle → export.
- **Not verifiable in the build sandbox:** Windows-specific behavior (`setup.bat`, winget ffmpeg, Thai font rendering under the user's ffmpeg build, tkinter picker, real transcription speed). These are documented in the README with troubleshooting, and expected to need a fix round after the user's first real run.

## 9. Install & run (Windows)

- Prerequisite: Python 3.11 or 3.12 (README gives the winget command).
- `setup.bat`: installs ffmpeg via `winget` if missing (the Gyan build includes libass), creates a venv, installs requirements.
- `run.bat`: starts the server on `127.0.0.1:<port>` and opens the browser.
- Whisper model downloads on first transcription (~3 GB for `large-v3`); the UI says so before starting.

## 10. Future (explicitly out of v1)

- Optional LLM module (off by default, user supplies an API key; text-only input): typo correction and bad-take/repeat removal.
- Optional cloud transcription backend.
- Thai fine-tuned Whisper models (require CTranslate2 conversion).
- Hardware encode (`h264_amf`) as an export option.

## 11. Risks / open items

- Real transcription speed on the 5700U is an estimate; model choice may need adjusting after measurement.
- libass Thai shaping depends on the user's ffmpeg build; verified only on the user's machine.
