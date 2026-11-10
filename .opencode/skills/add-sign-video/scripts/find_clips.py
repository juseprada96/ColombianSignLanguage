#!/usr/bin/env python3
"""Find every sign clip in a labeled sign-language video.

The helper watches a crop of the video where the sign's label is displayed,
detects label-change transitions, and emits one clip interval per sign. It also
extracts one indexed frame per clip so the labels can be transcribed.

Typical use (LSC Colombia layout, 854x480, label at top-right):

    python find_clips.py --video videos/finanzas.mp4 \
        --crop 540:145:280:80 --out-dir "$env:TEMP/csl-clips"

Read `sheet1.png`, `sheet2.png`, ... and write the labels into a words JSON:

    [
      {"key": "FINANZAS", "start": 3.966, "end": 7.85},
      ...
    ]

Then feed that file to add_signs.py with --words-file.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DEFAULT_FONT = r"C\:/Windows/Fonts/arialbd.ttf"


def run(cmd: list[str]) -> str:
    result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if result.returncode != 0:
        command = " ".join(shlex.quote(part) for part in cmd)
        raise SystemExit(result.stderr.strip() or f"command failed: {command}")
    return result.stdout


def difference_trace(video: Path, crop: str) -> list[tuple[float, float]]:
    # ``crop`` is user-friendly x:y:w:h; ffmpeg wants w:h:x:y.
    try:
        x, y, width, height = (int(part) for part in crop.split(":"))
    except ValueError as exc:
        raise SystemExit("--crop must be four integers: x:y:w:h") from exc
    ffmpeg_crop = f"{width}:{height}:{x}:{y}"
    cmd = [
        "ffmpeg", "-hide_banner", "-nostats", "-loglevel", "error",
        "-i", str(video),
        "-vf", f"crop={ffmpeg_crop},tblend=all_mode=difference,signalstats,metadata=print:file=-",
        "-an", "-f", "null", "-",
    ]
    output = run(cmd)

    current = None
    values: list[tuple[float, float]] = []
    for line in output.splitlines():
        match = re.search(r"pts_time:([0-9.]+)", line)
        if match:
            current = float(match.group(1))
        match = re.search(r"YAVG=([0-9.eE+-]+)", line)
        if match and current is not None:
            values.append((current, float(match.group(1))))
    return values


def merge_events(values, threshold: float, gap: float, min_peak: float, merge_gap: float):
    groups = []
    group = []
    for time, value in values:
        if value > threshold:
            if group and time - group[-1][0] > gap:
                groups.append(group)
                group = []
            group.append((time, value))
        elif group:
            groups.append(group)
            group = []
    if group:
        groups.append(group)

    groups = [g for g in groups if max(v for _, v in g) > min_peak]

    merged = []
    for group in groups:
        if merged and group[0][0] - merged[-1][1] < merge_gap:
            merged[-1] = (merged[-1][0], group[-1][0])
        else:
            merged.append((group[0][0], group[-1][0]))
    return merged


def extract_frame(video: Path, time: float, index: int, out: Path, width: int, font: str | None):
    filters = [f"scale={width}:-2"]
    if font:
        filters.append(
            f"drawtext=fontfile='{font}':text='{index}':x=8:y=8:"
            "fontsize=30:fontcolor=yellow:box=1:boxcolor=black@0.75"
        )
    run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostats", "-y",
        "-ss", f"{time:.3f}", "-i", str(video),
        "-vf", ",".join(filters), "-frames:v", "1", str(out),
    ])


def make_sheet(frames_dir: Path, start_number: int, out: Path, columns: int = 7, rows: int = 6):
    run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostats", "-y",
        "-framerate", "1", "-start_number", str(start_number),
        "-i", str(frames_dir / "%03d.png"),
        "-vf", f"tile={columns}x{rows}", "-frames:v", "1", str(out),
    ])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video", required=True, type=Path, help="Video file to inspect")
    parser.add_argument("--crop", required=True, help="Label crop as x:y:w:h")
    parser.add_argument("--out-dir", type=Path, help="Directory for clips.json, frames, and sheets")
    parser.add_argument("--threshold", type=float, default=1.2, help="Frame-difference threshold")
    parser.add_argument("--min-peak", type=float, default=5.0, help="Ignore weak label changes")
    parser.add_argument("--gap", type=float, default=0.12, help="Gap that separates difference bursts")
    parser.add_argument("--merge-gap", type=float, default=0.6, help="Merge fade-out/fade-in bursts")
    parser.add_argument("--width", type=int, default=400, help="Width of extracted frames")
    parser.add_argument("--font", default=DEFAULT_FONT, help="Font file for index labels; '' to disable")
    parser.add_argument("--keep-ends", action="store_true", help="Keep the intro and outro intervals as signs")
    args = parser.parse_args()

    if not args.video.is_file():
        raise SystemExit(f"Video not found: {args.video}")

    out_dir = args.out_dir or Path(tempfile.mkdtemp(prefix="csl-clips-"))
    frames_dir = out_dir / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    for old in frames_dir.glob("*.png"):
        old.unlink()

    print(f"Analyzing {args.video} with label crop {args.crop} ...")
    values = difference_trace(args.video, args.crop)
    if not values:
        raise SystemExit("No frame-difference data. Check --crop and that ffmpeg is installed.")

    merged = merge_events(values, args.threshold, args.gap, args.min_peak, args.merge_gap)
    if len(merged) < 2:
        raise SystemExit("Fewer than two label transitions found; adjust --crop or thresholds.")

    transitions = [(start + end) / 2 for start, end in merged]

    if args.keep_ends:
        starts = transitions
        ends = transitions[1:] + [merged[-1][0]]
    else:
        starts = transitions[1:-1]
        ends = starts[1:] + [merged[-1][0]]

    clips = []
    for index, (start, end) in enumerate(zip(starts, ends), 1):
        frame_time = (start + end) / 2
        frame_path = frames_dir / f"{index:03d}.png"
        extract_frame(args.video, frame_time, index, frame_path, args.width, args.font or None)
        clips.append({
            "index": index,
            "start": round(start, 3),
            "end": round(end, 3),
            "frame_time": round(frame_time, 3),
            "frame": str(frame_path),
        })
    print(f"extracted {len(clips)} frames")

    (out_dir / "clips.json").write_text(
        json.dumps(clips, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    with (out_dir / "clips.csv").open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=["index", "start", "end", "frame_time"])
        writer.writeheader()
        for clip in clips:
            writer.writerow({key: clip[key] for key in writer.fieldnames})

    sheet_size = 42
    sheets = math.ceil(len(clips) / sheet_size)
    for sheet in range(sheets):
        start_number = sheet * sheet_size + 1
        make_sheet(frames_dir, start_number, out_dir / f"sheet{sheet + 1}.png")

    print(f"clips: {len(clips)}")
    print(f"data:  {out_dir / 'clips.json'}")
    print(f"csv:   {out_dir / 'clips.csv'}")
    print(f"sheets: {', '.join(str(out_dir / f'sheet{i + 1}.png') for i in range(sheets))}")
    print("Next: transcribe every label from the sheets into a words JSON, then run add_signs.py --words-file.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
