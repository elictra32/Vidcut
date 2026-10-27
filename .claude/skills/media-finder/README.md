# 🎬 Media Finder

Turn a voiceover or script into a **shot-ready B-roll menu** — multiple free,
license-safe media options for every beat of your video, in one drop-in folder.

Built for short-form editors (Reels / TikTok / Shorts / YouTube) who want *choices
per moment*, not one AI guess — spanning **video, animated GIFs, transparent
graphics, and HD stills**, all sourced free and license-clear.

---

## What's in this bundle

| File | Use it if… |
|------|-----------|
| **`SKILL.md`** | You use **Claude Code, Claude.ai, or Cursor** (anything that loads Agent Skills). The full automated workflow — transcribe → beats → source → cue sheet → contact sheet. |
| **`PROMPT.md`** | You use **ChatGPT, Gemini, or any AI chat**. A copy-paste prompt — paste it, attach your clip/script, go. No install. |
| **`references/cue-sheet-template.md`** | The output format — the timestamp→file map you'll get back. |

Pick whichever matches your tool. They produce the same thing.

---

## Quick start

### Claude Code / Claude.ai / Cursor (Agent Skill)
1. Copy the whole `media-finder/` folder into your skills directory:
   - Claude Code: `~/.claude/skills/media-finder/`
   - Claude.ai / Cursor: upload the folder as a Skill (see your tool's Skills UI).
2. Then just say: *"find b-roll for this"* and attach your audio, video, or script.

### ChatGPT / Gemini / any chat
1. Open **`PROMPT.md`**, copy the block between the lines.
2. Paste it, attach your voiceover/video or paste your script, send.

---

## What you get back

A single flat folder per clip:

```
my-clip/
├── my-clip.srt              # timestamped transcript
├── cue-sheet.md             # timestamp → beat → files
├── contact-sheet.png        # montage to review at a glance
├── 01_hook_chaos-office.mp4 # beat 1 (the hook) — multiple options
├── 01_hook_facepalm.gif
├── 02_problem_a.png
└── …                        # numbered = running order
```

## The rules it follows

- **A menu, not a guess** — 2–4 options per beat, across media types.
- **The hook is sacred** — beat 1 gets extra options + why each stops the scroll.
- **Free & license-safe only** — Pexels (CC0), Iconify (MIT), Tenor (organic social).
  Flags Tenor for you if your video might be a paid ad.
- **One flat folder, named for the timeline** — number = order, no hunting.

---

## Sources & licensing

| Type | Source | License |
|------|--------|---------|
| Video + stills | Pexels | CC0 — safe to monetize |
| GIFs / memes | Tenor | Organic social only |
| Graphics / icons | Iconify | MIT — safe to monetize |

Transcription is **local & free** (Whisper / faster-whisper / mlx-whisper) — nothing
is uploaded, nothing is billed.

---

*MIT licensed. Share it, remix it. Built by an editor, for editors.*
