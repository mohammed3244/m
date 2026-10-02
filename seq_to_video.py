#!/usr/bin/env python3
"""Turn an image sequence folder into a video with ffmpeg.

Usage:
    python seq_to_video.py "C:/Users/gtava/OneDrive/Desktop/SARA/2/glow_fast"
    python seq_to_video.py <folder> --fps 24 --out glow_fast.mp4
    python seq_to_video.py <folder> --alpha          # ProRes 4444 .mov, keeps transparency

Requires ffmpeg on PATH (Windows: `winget install ffmpeg`).
"""
import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections import Counter

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".exr", ".bmp", ".tga", ".webp", ".dpx"}
FRAME_RE = re.compile(r"^(.*?)(\d+)$")


def natural_key(name):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", name)]


def find_frames(folder):
    files = [f for f in os.listdir(folder)
             if os.path.isfile(os.path.join(folder, f))
             and os.path.splitext(f)[1].lower() in IMAGE_EXTS]
    if not files:
        sys.exit(f"No image files found in {folder}")
    ext = Counter(os.path.splitext(f)[1].lower() for f in files).most_common(1)[0][0]
    frames = sorted((f for f in files if os.path.splitext(f)[1].lower() == ext), key=natural_key)
    return frames, ext


def numbered_pattern(frames):
    """Return (pattern, start_number) if frames are prefix + contiguous zero-padded numbers."""
    parsed = []
    for f in frames:
        stem, ext = os.path.splitext(f)
        m = FRAME_RE.match(stem)
        if not m:
            return None
        parsed.append((m.group(1), m.group(2), ext))
    prefixes = {p for p, _, _ in parsed}
    widths = {len(n) for _, n, _ in parsed}
    exts = {e for _, _, e in parsed}
    if len(prefixes) != 1 or len(widths) != 1 or len(exts) != 1:
        return None
    nums = [int(n) for _, n, _ in parsed]
    if nums != list(range(nums[0], nums[0] + len(nums))):
        return None
    prefix, width, ext = prefixes.pop(), widths.pop(), exts.pop()
    return f"{prefix.replace('%', '%%')}%0{width}d{ext}", nums[0]


def main():
    ap = argparse.ArgumentParser(description="Image sequence -> video")
    ap.add_argument("folder")
    ap.add_argument("--fps", type=float, default=30)
    ap.add_argument("--out", help="output file (default: <folder name>.mp4/.mov next to the folder)")
    ap.add_argument("--crf", type=int, default=16, help="H.264 quality, lower = better (default 16)")
    ap.add_argument("--alpha", action="store_true", help="ProRes 4444 .mov with alpha channel")
    args = ap.parse_args()

    if not shutil.which("ffmpeg"):
        sys.exit("ffmpeg not found on PATH. Install it (Windows: winget install ffmpeg) and reopen the terminal.")

    folder = os.path.abspath(args.folder)
    frames, ext = find_frames(folder)
    out = args.out or os.path.join(os.path.dirname(folder),
                                   os.path.basename(folder) + (".mov" if args.alpha else ".mp4"))

    cmd = ["ffmpeg", "-y"]
    if ext == ".exr":
        cmd += ["-apply_trc", "iec61966_2_1"]  # linear EXR -> sRGB
    list_file = None
    pattern = numbered_pattern(frames)
    if pattern:
        pat, start = pattern
        cmd += ["-framerate", str(args.fps), "-start_number", str(start),
                "-i", os.path.join(folder, pat)]
    else:
        # Non-contiguous or irregular names: feed an explicit ordered list.
        fd, list_file = tempfile.mkstemp(suffix=".txt", text=True)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            for f in frames:
                path = os.path.join(folder, f).replace("\\", "/").replace("'", r"'\''")
                fh.write(f"file '{path}'\n")
        cmd += ["-f", "concat", "-safe", "0", "-r", str(args.fps), "-i", list_file]

    if args.alpha:
        cmd += ["-c:v", "prores_ks", "-profile:v", "4444", "-pix_fmt", "yuva444p10le"]
    else:
        cmd += ["-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2",  # H.264 needs even dimensions
                "-c:v", "libx264", "-preset", "slow", "-crf", str(args.crf),
                "-pix_fmt", "yuv420p", "-movflags", "+faststart"]
    cmd += ["-r", str(args.fps), out]

    print(f"{len(frames)} {ext} frames @ {args.fps} fps -> {out}")
    try:
        subprocess.run(cmd, check=True)
    finally:
        if list_file:
            os.remove(list_file)
    print(f"Done: {out}")


if __name__ == "__main__":
    main()
