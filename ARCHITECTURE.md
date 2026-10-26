# Vidcut architecture

Local web app: a Python backend (FastAPI) serves a build-less ES-module frontend. All media work is ffmpeg;
speech-to-text is faster-whisper on CPU. No LLM, no cloud. UI strings are Thai.
Specs and the plan that produced this code: `docs/superpowers/specs/` and `docs/superpowers/plans/`.

## Layout

```
core/    pure logic, no web code, unit-tested          server/  thin FastAPI glue + background jobs
  models.py     dataclasses (Project, Clip, Keep, Subtitle, ...)   app.py           routes, create_app(), run_server()
  media.py      ffprobe/ffmpeg runner, proxy, Cancelled/NoAudio     jobs.py          JobRunner (threads, progress, SSE)
  silence.py    silencedetect -> keeps                              project_store.py project.json, atomic write
  waveform.py   peak envelope for drawing                          errors.py        AppError -> Thai message + hint
  timeline.py   source <-> edited time mapping                      fake_whisper.py  canned transcript (VIDCUT_FAKE_WHISPER=1)
  thai_split.py Whisper tokens -> Thai words -> subtitle lines
  transcribe.py faster-whisper wrapper; autosub.py selection -> Subtitle[]
  ass.py        ASS + SRT output; presets.py  TikTok/YouTube
  fonts.py      bundled font list + CSS-size -> libass-Fontsize factor
  export.py     ffmpeg filter graph, run_export, render_preview_frame
web/     one ES module per concern (state.js is the store; timeline_math.js mirrors core/timeline.py)
fonts/   Sarabun + Prompt (SIL OFL), used by the browser preview AND the ffmpeg export
tests/   pytest (tests/), node tests (tests/js), Playwright smoke test (tests/e2e)
```

`core/` never imports `server/` or `web/`. `web/` talks to `server/` only over HTTP/JSON and SSE.

## The rules that matter

1. **Two time axes.** *Source time* = seconds in a clip's file. *Edited time* = the enabled keeps of all clips,
   concatenated in order (dead air removed). `core/timeline.py` owns every conversion; `web/timeline_math.js` is a
   port kept honest by `tests/fixtures/timeline_cases.json`, which both test suites run. Change one, change both.
2. **Subtitles are source-anchored** (`clip_id, src_start, src_end`). Edited time is always derived, so toggling a cut
   never desyncs a subtitle from its speech. The selection (In/Out) is stored in edited time and is remapped to the
   same source content whenever keeps change (`remapSelection` / `updateKeeps` in the web code).
3. **`Keep.enabled=false` = cut.** Dead-air gaps are the complement of the keeps; clicking a gap adds a keep for it.
4. **Source files are never modified or copied.** Projects store paths. Browsers that can't play a file get a 480p proxy.
5. **Export is frame-exact and batched.** Each selected piece is its own seeked input (`-ss/-t -i`), so a selection
   at minute 40 of a one-hour file doesn't decode 40 minutes. Every piece is cut to a whole number of output frames
   (30 fps) and `n*1600` audio samples, with boundaries rounded *cumulatively* from the exact edited times
   (`frame_counts`); otherwise each cut leaves a frame or two and subtitles drift by seconds over a cut-heavy short.
   More than `BATCH` (12) pieces are rendered in batches to scratch parts, then one pass joins them and burns the
   subtitles: every input costs a decoder (~45 MB) and Windows caps a command line at 32k characters. Graphs are
   passed inline (`-filter_complex`; `-filter_complex_script` is deprecated in FFmpeg 7+). ffmpeg runs with `cwd` =
   a temp dir and refers to `subs.ass` and `fonts` by relative name (absolute paths inside filter strings are a Windows
   escaping trap). Outputs never overwrite earlier ones (`name_tiktok.mp4`, `name_tiktok_2.mp4`, ...).
6. **Preview vs export.** Subtitle x/y are fractions of the *export* frame (preset aspect). The preview draws them in
   CSS (`web/stage.js: style()`), the export in ASS (`core/ass.py: _style_line`). `style.size` is the CSS em size in
   output pixels; libass `Fontsize` is the font's whole line height (OS/2 win ascent+descent), so
   `core/fonts.py: ass_size_factor` converts it (Sarabun is 1.85x). A test compares libass against an independent
   FreeType render. Every offered font must resolve in libass by its own name (tested). "ตรวจเฟรมจริง" renders one
   real frame through the export graph.
7. **Jobs and the project.** Long work (proxy, silence, transcribe, export) runs as a job; proxies get their own pool
   so they never starve the rest. Jobs read a snapshot and write results into the server's project under a lock,
   bumping `project.rev`. `PUT /api/project` is refused with 409 `project_stale` when its `rev` is old, and the page
   reloads instead of overwriting a job's result. The server owns everything about the media (path, proxy, size,
   duration) and clips only enter through `/api/clips`; the page owns keeps, framing, subtitles, style, selection.
   The UI flushes its pending save *before* starting a job and re-fetches (`reloadAfterJob`) after it.
   The server answers only to `127.0.0.1`/`localhost` Hosts and refuses cross-origin writes (DNS rebinding / CSRF).
8. **Errors are Thai, with a fix.** Raise `AppError(code, message, hint, details)` or let `from_exception` map core
   exceptions; the UI shows message + hint and folds `details` away.

## Testing

- `pytest`: all of `core/` and the HTTP layer, using synthetic media from `tests/helpers.py` (ffmpeg lavfi) and an
  injected fake Whisper model. Export tests need an ffmpeg with libass (skipped otherwise).
- `node --test "tests/js/*.test.mjs"`: the JS time-mapping port, from the shared fixtures.
- `tests/e2e/smoke.mjs`: real server + Chromium + fake Whisper through add clip -> silence -> select -> subtitles ->
  edit -> export. `multiclip.mjs`: playback continues across clips. Both use WebM (Playwright's Chromium lacks H.264)
  and share `harness.mjs`.
- The real-Whisper test is marked `slow` and needs a model download.

## Adding an LLM step later (typo fixing, bad-take removal)

Keep it optional and text-only. Add `core/llm.py` with a function over `list[Subtitle]` (text in, text out, user-supplied
API key from env/settings), call it from a new job in `server/app.py`, and a button in `web/subtitles.js`. Nothing in
the current pipeline needs to change, and nothing here should ever send video or audio to a service.

## Known limits

Not verified on Windows or with a real Whisper model at the time of writing. The live preview shows letterbox bars,
not the blurred background, for `blur_fit`. No user-saved style presets. `crop` only moves horizontally.
