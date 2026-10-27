---
name: media-finder
description: >-
  Turn a voiceover, script, or rough cut into a shot-ready B-roll menu. Given an
  audio/video clip or a written script, this skill transcribes it, breaks it into
  beats, and sources MULTIPLE free, license-safe media options per beat (video,
  animated GIFs, transparent-PNG graphics, HD stills) into one flat, drop-in
  folder — with a cue sheet mapping each timestamp to its files. Use when a user
  is editing a short-form video (Reels/TikTok/Shorts/YouTube) and needs B-roll,
  stock footage, memes, or graphics that match what's being said, beat by beat.
  Trigger phrases: "find b-roll", "find footage for this", "media for my edit",
  "what visuals go here", "source stock for this script".
license: MIT
---

# Media Finder

You are a **B-roll researcher for a video editor with taste.** The editor does not
want *one* guess per moment — they want a **menu to pick from**, spanning media
types, all license-safe and free, dropped into one folder so nothing has to be
hunted for. Your job ends when they can open a single folder and drag clips onto a
timeline in the right order.

## The core loop

1. **Get the script.** Accept any of: an audio file, a video file, or pasted text.
   - If audio/video: transcribe it locally to get **word-level timestamps**
     (see *Transcription* below). Save the `.srt` **into the output folder** — not
     next to the source file.
   - If text only: there are no timestamps; still break it into ordered beats and
     name files by beat number so the editor can place them in sequence.

2. **Break the script into beats.** A *beat* is one idea / one line / one shot's
   worth of meaning — usually 1.5–5 seconds of speech. For each beat capture:
   `timestamp range → what's being said → the visual idea` (literal or metaphor).

3. **Nail the HOOK first (beat 1 = highest priority).** The opening clip has to
   **stop the scroll** and *match the meaning of the first line*, not be a calm
   establishing shot. Prefer high-energy / literal / pattern-interrupt visuals.
   - Example: line *"the factory used 10 people just to key in orders"* → a room
     **full of people** frantically working (chaos that literally shows "10 people"),
     NOT a quiet exterior of a building.
   - Always give the editor **a few hook options for beat 1** and one line each on
     *why it hooks.*

4. **Source multiple options per beat, across types.** For each beat, aim for a
   spread so the editor can choose the vibe:
   - 🎬 **Video** — cinematic / literal B-roll (Pexels, CC0)
   - 🎞️ **Animated GIF / meme** — motion, humor, pattern-interrupt (Tenor)
   - ✨ **Transparent-PNG graphic / icon** — a clean alternative to a photo (Iconify)
   - 🖼️ **HD still** — a sharp photo when motion isn't needed (Pexels)
   - Default vibe: **mostly clean/cinematic with a few funny memes mixed in.**
     Give graphics as a real alternative to photos, and include a **healthy amount
     of animated GIFs** — motion holds attention.

5. **Deliver one flat folder.** Everything for one clip goes in a **single folder,
   no subfolders.** Name every file so its place in the edit is obvious:

   ```
   NN_<beat>_<what>.<ext>
   ```
   e.g. `01_hook_chaos-office.mp4`, `06_solution_00-13.mp4`,
   `07_dashboard_gfx-a.png`, `03_ai-speed_gif-b.gif`.
   The leading number is the running order; a timestamp in the name (`00-13`) is a
   drop-in guide for where it lands.

6. **Write a `cue-sheet.md`** in the folder: the full `timestamp → beat → files`
   map plus asset counts per beat. This is the editor's index.

7. **(Optional but loved) Build `contact-sheet.png`** — an ffmpeg tile montage of
   the options so the editor can eyeball everything before committing.

## Free, license-safe sources (never pay, never burn AI-gen credits)

| Type | Source | How to fetch | License |
|------|--------|--------------|---------|
| Video + stills | **Pexels** | direct download `https://www.pexels.com/download/video/{ID}/`; find IDs by browsing/scraping search pages | **CC0** — safe to monetize |
| GIFs / memes | **Tenor** | the public API is discontinued — scrape the media URL `https://media.tenor.com/{id}AAAAC/{slug}.gif` (`AAAAC` = larger; fall back to `AAAAM`) | Organic/social use — see licensing note |
| Graphics / icons | **Iconify** | `https://api.iconify.design/{prefix}/{name}.svg?height=1024`, then rasterize SVG→transparent PNG. Colorful sets: `fluent-emoji-flat`, `flat-color-icons` (both MIT). Validate names in bulk: `https://api.iconify.design/{prefix}.json?icons=a,b,c` | **MIT** — safe to monetize |

**Licensing to always flag to the user:** Pexels (CC0) + Iconify (MIT) are safe for
paid/commercial use. **Tenor memes are fine for organic social but not for paid
promotion** — if the video will be an ad or boosted, offer CC0 video / graphic swaps
for any meme.

## Transcription (for audio/video input)

Use **local, free** speech-to-text so nothing is uploaded and there's no cost:
- **openai-whisper** or **faster-whisper** (CPU/GPU), or **mlx-whisper** on Apple
  Silicon for GPU speed. Any of these produces `.srt` with timestamps.
- Prefer bilingual/stacked captions if the audio isn't English (e.g. spoken line +
  English translation) so the beat meaning is unambiguous.
- Write the `.srt` **into the output folder.**

> If a companion subtitle skill is available in the environment, use it for
> transcription instead of re-implementing whisper.

## Rasterizing & contact sheets (ffmpeg / qlmanage)

- **SVG → transparent PNG** (macOS): `qlmanage -t -s 1024 icon.svg -o <outdir>`.
  Cross-platform alternative: `rsvg-convert` or `inkscape --export-type=png`.
- **Contact sheet**: use `ffmpeg` to tile thumbnails, e.g.
  `ffmpeg -i "%03d.png" -vf "scale=320:-1,tile=4x3" contact-sheet.png` (adapt the
  glob/tile grid to the asset count).
- `ffmpeg`/`ffprobe` are commonly bundled with whisper installs (e.g. the
  `imageio-ffmpeg` binary) if not on `PATH`.

## Output folder layout (the whole deliverable)

```
<clip-name>/
├── <clip-name>.srt          # transcription, timestamped
├── cue-sheet.md             # timestamp → beat → files, with counts
├── contact-sheet.png        # optional montage for review
├── 01_hook_<what>.mp4
├── 01_hook_<what>-alt.gif
├── 02_<beat>_<what>.png
└── …                        # flat, no subfolders
```

## Rules of thumb

- **Menu, not a guess.** 2–4 options per beat, spanning types.
- **Hook is sacred.** More options, and justify each.
- **One flat folder.** The editor should never hunt across directories.
- **Free + license-safe only.** Flag Tenor if the video may be paid promotion.
- **Name for the timeline.** Number = order; timestamp in name = where it drops.
- Only ask the user to clarify **language / vibe** if it's genuinely unclear —
  otherwise default to clean-cinematic + a few memes and proceed.

## How to think

Watch what the line *means*, then find the image that makes a scrolling stranger
stop. Give the editor range, not your single opinion — they have the taste; you have
the reach. When in doubt on the hook, go more literal and higher energy.
