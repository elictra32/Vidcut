# Vidcut

Read `ARCHITECTURE.md` before changing `core/`, `server/` or `web/`. Tests: `pytest`, `node --test "tests/js/*.test.mjs"`.

## Editing skills

Eight third-party editing skills are pinned in `tools/skills.json` and installed with `python tools/install_skills.py install`
into `.claude/skills/` and `third_party/` (both git-ignored). Which one for which job: `docs/skills.md`.
Rules when editing a user's footage with them: work on a copy, never the original; report measured numbers
(seconds, percent, HEX), not "fast"; say "not sure" instead of guessing (fonts, colours); copy a reference clip's
style and technique only, never its content, music or the owner's footage.
