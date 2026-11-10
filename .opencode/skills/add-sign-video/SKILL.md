---
name: Add Sign Video
description: Add every sign from a video to this dictionary. Downloads a medium-quality copy with yt-dlp, detects all sign clips, exports each as a 384px/10fps GIF, and updates words/manifest.json plus vocabulary.json.
---

# Add Sign Video

Use this skill when the user wants to add signs from a video (YouTube, Drive, a
local file, etc.) to the project. It downloads a medium-quality copy of the
video and registers **every** requested sign in both data files.

Do **not** use it to edit `frases.json`: phrases are curated separately.

## Scope: always add all signs

**Add every sign shown in the video by default.** Do not add a sample, a
"representative few", or only the words you personally recognise. When the user
gives only a URL, that is still an instruction to add the whole video.

Only omit a sign when the user explicitly names it or asks for a partial run.
If the video contains a long sequence (numbers, a full alphabet, etc.), process
it as one batch with `--words-file`; do not drip-feed entries.

## Conventions to preserve

| Thing              | Rule                                                                 |
| ------------------ | -------------------------------------------------------------------- |
| Videos             | Go in `videos/`, which is gitignored. Never commit them.             |
| GIFs               | `words/<SECTION_FOLDER>/<WORD_SLUG>.gif`                             |
| Section folder     | Uppercase, accents removed, spaces → `_` (`VERBOS 1` → `VERBOS_1`)    |
| Word slug          | Uppercase, accents removed, non-alphanumerics → `_` (`PAPÁ` → `PAPA`) |
| GIF format         | 384 px wide, 10 fps, infinite loop (matches existing assets)         |
| `vocabulary.json`  | `{ "<Section>": { "<KEY>": "words/<FOLDER>/<SLUG>.gif" } }`          |
| Manifest entry     | `{ key, section, gif, video, start, end, label }`                    |

Existing entries use the display section name (spaces allowed) in
`vocabulary.json` and `words/manifest.json`, while folders and GIF filenames use
underscores. `label` is normally `null`.

## Inputs

Collect only what is genuinely missing. Do not ask the user to transcribe the
video for you:

1. **Video URL** and a short **video filename** (for example `finanzas.mp4`).
2. **Section** name exactly as it should appear in the UI (for example `FINANZAS`).
3. **Every word and timestamp.** If the user supplies them, use them. Otherwise
   derive all of them with the full-video sweep below.

## Full-video sweep (default when timestamps are missing)

1. **Download** at medium quality first. Running the helper once with a
   placeholder word is not enough; call `yt-dlp` directly or let
   `add_signs.py` download during the batch.

   ```powershell
   python -m yt_dlp --no-playlist -f "bv*+ba/b" -S "res:480,ext:mp4:m4a" `
     --merge-output-format mp4 -o videos/finanzas.mp4 "https://..."
   ```

2. **Locate the label area.** Most LSC Colombia videos show the sign name in the
   top-right corner. For a 854×480 video the crop is usually `540:145:280:80`.
   Check a frame and adjust if the layout differs.

3. **Detect every clip.** The helper watches the label crop, finds every
   label-change transition, and extracts one indexed frame per sign:

   ```powershell
   python .opencode/skills/add-sign-video/scripts/find_clips.py `
     --video videos/finanzas.mp4 `
     --crop 540:145:280:80 `
     --out-dir "$env:TEMP\csl-clips"
   ```

   It writes `clips.json`, `clips.csv`, indexed frames, and `sheet1.png`,
   `sheet2.png`, ... Read the sheets and transcribe **every** label. Do not skip
   labels that look like numbers or duplicates; use the displayed text as the
   key unless the user asks for spoken-out names.

4. **Build the batch file** with one entry per detected clip (`clips.csv` has the
   exact `start`/`end` values):

   ```json
   [
     { "key": "FINANZAS", "start": 3.966, "end": 7.85 },
     { "key": "NÚMEROS", "start": 7.85, "end": 12.466 }
   ]
   ```

   Verify the JSON length equals the number of clips the helper reported.

5. **Add every clip in one run.** Use `--replace` when re-cutting a section so
   old GIFs and new timestamps stay consistent:

   ```powershell
   python .opencode/skills/add-sign-video/scripts/add_signs.py `
     --section FINANZAS --video finanzas.mp4 --skip-download --replace `
     --words-file "$env:TEMP\csl-clips\words.json"
   ```

6. **Verify.** The script prints every GIF path and validates the JSON. Also check:

   ```powershell
   git status --short
   git diff --stat -- vocabulary.json words/manifest.json
   ```

   Only GIFs and the two JSON files should change. `videos/` must not appear.
   Confirm the section's word count matches the number of clips.

## Adding a few explicit words

When the user already provides exact words and timestamps, skip the sweep and
run the helper directly. This is the only case where a partial set is allowed.

```powershell
python .opencode/skills/add-sign-video/scripts/add_signs.py `
  --section FAMILIA `
  --video familia.mp4 `
  --url "https://www.youtube.com/watch?v=..." `
  --word "PAPÁ=8.5-14.0" `
  --word "MAMÁ=14.0-19.25"
```

Re-running with the same word updates the existing entry instead of duplicating
it. Use `--skip-download` when the video is already present.

## Format notes

The medium-quality download uses `yt-dlp -f "bv*+ba/b" -S "res:480"` so it never
pulls 1080p/4K unnecessarily. GIFs are palette-optimized to keep them small
enough for GitHub Pages. If a clip looks choppy, adjust `--fps`; if a page feels
heavy, keep 10 fps and 384 px rather than increasing them.

## Failure handling

- The URL has no stream ≤ 480p: `yt-dlp` falls back to the closest available
  resolution. Warn the user if the source is much larger.
- A clip is the wrong sign: re-run the word with corrected timestamps; the
  helper overwrites the GIF and updates the same entry.
- The GIF is all black/blank: re-check the source time range and the video
  filename before blaming the helper.
- `find_clips.py` finds too many or too few clips: adjust `--crop` first, then
  `--min-peak` (raise it to ignore hand motion) or `--merge-gap` (raise it to
  join a slow fade). Use `--keep-ends` if the video starts or ends directly on a
  sign instead of an intro/outro card.
