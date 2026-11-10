#!/usr/bin/env python3
"""Add sign-language words from a video to the ColombianSignLanguage project.

Downloads a medium-quality copy (when a URL is given), exports each word
interval as a GIF, and upserts the word in vocabulary.json and
words/manifest.json.

Example:
    python scripts/add_signs.py --section FAMILIA --video familia.mp4 \
        --url https://www.youtube.com/watch?v=... \
        --word "PAPÁ=8.5-14.0" --word "MAMÁ=14.0-19.25"
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import shutil
import subprocess
import sys
import unicodedata
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def find_repo_root(start: Path) -> Path:
    for directory in (start, *start.parents):
        if (directory / "vocabulary.json").is_file() and (
            directory / "words" / "manifest.json"
        ).is_file():
            return directory
    raise SystemExit("Could not locate the project root (vocabulary.json + words/manifest.json).")


def slugify(value: str) -> str:
    """Uppercase, strip accents, and turn runs of non-alphanumerics into '_'."""
    decomposed = unicodedata.normalize("NFD", value)
    without_accents = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return re.sub(r"[^A-Za-z0-9]+", "_", without_accents).strip("_").upper()


def parse_word(text: str) -> dict:
    try:
        key, times = text.rsplit("=", 1)
        start_text, end_text = times.rsplit("-", 1)
        start, end = float(start_text), float(end_text)
    except ValueError as exc:
        raise SystemExit(f"Bad --word {text!r}; expected KEY=START-END") from exc
    if start < 0 or end <= start:
        raise SystemExit(f"Bad times for {key!r}: end must be greater than start")
    return {"key": key.strip(), "start": start, "end": end}


def load_words_file(path: Path) -> list[dict]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"Could not read {path}: {exc}") from exc
    if not isinstance(data, list):
        raise SystemExit(f"{path} must contain a JSON array of word objects")

    words = []
    for item in data:
        try:
            key = str(item["key"]).strip()
            start = float(item["start"])
            end = float(item["end"])
        except (KeyError, TypeError, ValueError) as exc:
            raise SystemExit(f"Bad word entry in {path}: {item!r}") from exc
        if start < 0 or end <= start:
            raise SystemExit(f"Bad times for {key!r}: end must be greater than start")
        words.append({"key": key, "start": start, "end": end})
    return words


def run(cmd: list[str]) -> None:
    print("+", " ".join(cmd))
    subprocess.run(cmd, check=True)


def yt_dlp_command() -> list[str]:
    executable = shutil.which("yt-dlp")
    if executable:
        return [executable]
    if importlib.util.find_spec("yt_dlp"):
        return [sys.executable, "-m", "yt_dlp"]
    raise SystemExit(
        "yt-dlp is not installed. Install it with 'winget install yt-dlp' "
        "or 'python -m pip install -U yt-dlp'."
    )


def ffmpeg_command() -> str:
    executable = shutil.which("ffmpeg")
    if not executable:
        raise SystemExit("ffmpeg is not installed or not on PATH.")
    return executable


def download(url: str, video_path: Path, force: bool) -> None:
    if video_path.exists() and not force:
        print(f"Using existing video: {video_path}")
        return

    cmd = yt_dlp_command() + [
        "--no-playlist",
        "-f",
        "bv*+ba/b",
        "-S",
        "res:480,ext:mp4:m4a",
        "--merge-output-format",
        "mp4",
        "-o",
        str(video_path),
    ]
    if force:
        cmd.append("--force-overwrites")
    run(cmd + [url])
    if not video_path.exists():
        raise SystemExit(f"yt-dlp finished but {video_path} was not created")


def make_gif(ffmpeg: str, video_path: Path, gif_path: Path, start: float, end: float, fps: int, width: int) -> None:
    duration = end - start
    filters = (
        f"fps={fps},scale={width}:-2:flags=lanczos,"
        "split[s0][s1];"
        "[s0]palettegen=stats_mode=diff[p];"
        "[s1][p]paletteuse=dither=bayer:bayer_scale=5:diff_mode=rectangle"
    )
    gif_path.parent.mkdir(parents=True, exist_ok=True)
    run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-nostats",
            "-y",
            "-ss",
            f"{start:.3f}",
            "-t",
            f"{duration:.3f}",
            "-i",
            str(video_path),
            "-vf",
            filters,
            "-loop",
            "0",
            str(gif_path),
        ]
    )


def write_json(path: Path, data: object) -> None:
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--section", required=True, help="Section name as shown in the UI, e.g. FAMILIA")
    parser.add_argument("--video", required=True, help="Filename inside videos/, e.g. familia.mp4")
    parser.add_argument("--url", help="Video URL; required when videos/<video> is missing")
    parser.add_argument("--word", action="append", default=[], metavar="KEY=START-END", help="Word and time range; repeatable")
    parser.add_argument("--words-file", type=Path, help="JSON array of {key, start, end} objects")
    parser.add_argument("--label", default=None, help="Optional manifest label (default: null)")
    parser.add_argument("--fps", type=int, default=10, help="GIF frame rate (default: 10)")
    parser.add_argument("--width", type=int, default=384, help="GIF width in pixels (default: 384)")
    parser.add_argument("--skip-download", action="store_true", help="Never download; fail if the video is missing")
    parser.add_argument("--replace", action="store_true", help="Re-cut GIFs that already exist")
    args = parser.parse_args()

    words = [parse_word(text) for text in args.word]
    if args.words_file:
        words.extend(load_words_file(args.words_file))
    if not words:
        parser.error("provide at least one --word or --words-file")

    seen: set[str] = set()
    for word in words:
        slug = slugify(word["key"])
        if not slug:
            parser.error(f"cannot derive a filename from {word['key']!r}")
        if slug in seen:
            parser.error(f"duplicate word in this run: {word['key']!r}")
        seen.add(slug)
        word["slug"] = slug

    root = find_repo_root(Path(__file__).resolve().parent)
    videos_dir = root / "videos"
    section_folder = slugify(args.section)
    if not section_folder:
        parser.error(f"cannot derive a folder from section {args.section!r}")

    video_name = Path(args.video).name
    if video_name != args.video:
        parser.error("--video must be a filename without directories")
    video_path = videos_dir / video_name

    if args.skip_download and not video_path.exists():
        raise SystemExit(f"--skip-download given but {video_path} does not exist")
    if not video_path.exists() and not args.url:
        raise SystemExit(f"{video_path} does not exist; pass --url to download it")

    if not args.skip_download:
        videos_dir.mkdir(parents=True, exist_ok=True)
        download(args.url, video_path, force=args.replace)

    ffmpeg = ffmpeg_command()

    vocab_path = root / "vocabulary.json"
    manifest_path = root / "words" / "manifest.json"
    vocabulary = json.loads(vocab_path.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    section_words = vocabulary.setdefault(args.section, {})
    created = []

    for word in words:
        key, slug, start, end = word["key"], word["slug"], word["start"], word["end"]
        gif_rel = f"words/{section_folder}/{slug}.gif"
        gif_path = root / gif_rel

        if gif_path.exists() and not args.replace:
            print(f"Keeping existing GIF: {gif_rel} (use --replace to re-cut)")
        else:
            make_gif(ffmpeg, video_path, gif_path, start, end, args.fps, args.width)

        section_words[key] = gif_rel

        entry = {
            "key": key,
            "section": args.section,
            "gif": gif_rel,
            "video": video_name,
            "start": round(start, 3),
            "end": round(end, 3),
            "label": args.label,
        }
        for index, existing in enumerate(manifest):
            if existing.get("key") == key and existing.get("section") == args.section:
                manifest[index] = entry
                break
        else:
            manifest.append(entry)

        created.append((key, gif_rel, gif_path.stat().st_size))

    write_json(vocab_path, vocabulary)
    write_json(manifest_path, manifest)

    print("\nAdded/updated:")
    for key, gif_rel, size in created:
        print(f"  {key:<24} {gif_rel}  ({size / 1024:.0f} KiB)")

    if not any(section_words):
        raise SystemExit(f"Section {args.section!r} ended up empty")

    print(f"\nOK: {len(created)} word(s) in section {args.section!r}; video: videos/{video_name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
