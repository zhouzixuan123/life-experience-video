#!/usr/bin/env python3
"""Prove that SRT captions are visibly burned into the delivered video."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from caption_utils import clean_caption_text, display_units
from font_utils import resolve_font


WIDTH = 640
HEIGHT = 360
TIME_RE = re.compile(r"(\d{2}):(\d{2}):(\d{2})[,.](\d{3})\s+-->\s+(\d{2}):(\d{2}):(\d{2})[,.](\d{3})")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def seconds(values: tuple[str, str, str, str]) -> float:
    hours, minutes, secs, millis = map(int, values)
    return hours * 3600 + minutes * 60 + secs + millis / 1000


def cues(path: Path) -> list[dict]:
    result = []
    blocks = re.split(r"\r?\n\s*\r?\n", path.read_text(encoding="utf-8-sig").strip())
    for block in blocks:
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        time_index = next((index for index, line in enumerate(lines) if TIME_RE.fullmatch(line)), None)
        if time_index is None:
            continue
        match = TIME_RE.fullmatch(lines[time_index])
        result.append({
            "start": seconds(match.groups()[:4]),
            "end": seconds(match.groups()[4:]),
            "text": "".join(lines[time_index + 1 :]),
        })
    return result


def sample(items: list[dict], count: int) -> list[dict]:
    if len(items) <= count:
        return items
    last = len(items) - 1
    return [items[round(index * last / (count - 1))] for index in range(count)]


def frame(ffmpeg: Path, source: Path, timestamp: float) -> bytes:
    process = subprocess.run(
        [
            str(ffmpeg), "-v", "error", "-ss", f"{timestamp:.6f}", "-i", str(source),
            "-frames:v", "1", "-vf",
            f"scale={WIDTH}:{HEIGHT}:flags=bilinear,format=gray",
            "-f", "rawvideo", "pipe:1",
        ], capture_output=True,
    )
    if process.returncode or len(process.stdout) != WIDTH * HEIGHT:
        raise RuntimeError(process.stderr.decode("utf-8", errors="replace"))
    return process.stdout


def difference(first: bytes, second: bytes) -> float:
    return sum(abs(a - b) for a, b in zip(first, second)) / (len(first) * 255.0)


def difference_bbox(first: bytes, second: bytes, threshold: int = 18) -> list[int] | None:
    points = [index for index, (a, b) in enumerate(zip(first, second)) if abs(a - b) >= threshold]
    if not points:
        return None
    xs = [index % WIDTH for index in points]
    ys = [index // WIDTH for index in points]
    return [min(xs), min(ys), max(xs), max(ys)]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("project_dir", type=Path)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--reference", type=Path)
    parser.add_argument("--srt", type=Path)
    parser.add_argument("--ffmpeg", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--sample-count", type=int, default=12)
    parser.add_argument("--minimum-difference", type=float, default=0.0015)
    parser.add_argument("--max-caption-units", type=float, default=15.0)
    parser.add_argument("--font-size", type=int, default=60)
    parser.add_argument("--horizontal-margin", type=int, default=120)
    parser.add_argument("--bottom-margin", type=int, default=54)
    args = parser.parse_args()

    project = args.project_dir.resolve()
    work = project / "work"
    source = (args.source or work / "remix.mp4").resolve()
    reference = (args.reference or work / "video_without_captions.mp4").resolve()
    srt = (args.srt or work / "captions.srt").resolve()
    ffmpeg = args.ffmpeg.resolve()
    output = (args.output or work / "caption_render_validation.json").resolve()
    for path in (source, reference, srt, ffmpeg):
        if not path.is_file():
            raise FileNotFoundError(path)

    all_cues = cues(srt)
    selected = sample([cue for cue in all_cues if cue["end"] - cue["start"] >= 0.12], max(2, args.sample_count))
    font = ImageFont.truetype(str(resolve_font("bold")), args.font_size)
    probe = ImageDraw.Draw(Image.new("L", (1, 1)))
    safe_text_width = 1920 - 2 * args.horizontal_margin
    cue_checks = []
    for index, cue in enumerate(all_cues, 1):
        text = clean_caption_text(cue["text"])
        pixel_width = float(probe.textlength(text, font=font))
        cue_checks.append({
            "index": index,
            "text": text,
            "units": round(display_units(text), 2),
            "pixel_width": round(pixel_width, 2),
            "single_line": "\n" not in cue["text"] and "\r" not in cue["text"],
            "units_safe": display_units(text) <= args.max_caption_units + 1e-6,
            "pixel_width_safe": pixel_width <= safe_text_width,
        })
    samples = []
    scaled_margin_x = round(args.horizontal_margin / 1920 * WIDTH)
    scaled_bottom = round(args.bottom_margin / 1080 * HEIGHT)
    for cue in selected:
        timestamp = cue["start"] + min(cue["end"] - cue["start"], 0.5) * 0.5
        source_frame, reference_frame = frame(ffmpeg, source, timestamp), frame(ffmpeg, reference, timestamp)
        score = difference(source_frame, reference_frame)
        bbox = difference_bbox(source_frame, reference_frame)
        inside = bool(bbox) and bbox[0] >= scaled_margin_x - 4 and bbox[2] <= WIDTH - scaled_margin_x + 4 and bbox[3] <= HEIGHT - 4
        bottom_position_ok = bool(bbox) and bbox[3] >= HEIGHT - scaled_bottom - round(args.font_size / 1080 * HEIGHT * 1.8)
        samples.append({"time": round(timestamp, 6), "difference": round(score, 6), "caption_visible": score >= args.minimum_difference, "difference_bbox": bbox, "inside_horizontal_safe_area": inside, "bottom_position_ok": bottom_position_ok})

    checks = {
        "srt_has_cues": bool(all_cues),
        "caption_samples_exist": bool(samples),
        "captions_visible_in_all_sampled_regions": bool(samples) and all(item["caption_visible"] for item in samples),
        "all_cues_are_single_line": bool(cue_checks) and all(item["single_line"] for item in cue_checks),
        "all_cues_fit_display_unit_limit": bool(cue_checks) and all(item["units_safe"] for item in cue_checks),
        "all_cues_fit_measured_pixel_width": bool(cue_checks) and all(item["pixel_width_safe"] for item in cue_checks),
        "sampled_captions_stay_inside_horizontal_safe_area": bool(samples) and all(item["inside_horizontal_safe_area"] for item in samples),
        "sampled_captions_use_bottom_caption_zone": bool(samples) and all(item["bottom_position_ok"] for item in samples),
    }
    report = {
        "passed": all(checks.values()),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source": str(source), "source_sha256": sha256(source),
        "reference": str(reference), "reference_sha256": sha256(reference),
        "srt": str(srt), "srt_sha256": sha256(srt),
        "cue_count": len(all_cues), "style": {"font_size_px": args.font_size, "horizontal_margin_px": args.horizontal_margin, "bottom_margin_px": args.bottom_margin, "max_caption_units": args.max_caption_units}, "checks": checks, "cue_checks": cue_checks, "samples": samples,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
