#!/usr/bin/env python3
"""Validate body-shot push-ins in both the recipe and the rendered video."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import statistics
import subprocess
from datetime import datetime, timezone
from pathlib import Path


BODY_SHOT = re.compile(r"^S\d{3,}$")
FRAME_WIDTH = 320
FRAME_HEIGHT = 132


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def shot_times(shot: dict) -> tuple[float, float]:
    start = float(shot.get("start_seconds", 0.0))
    if "end_seconds" in shot:
        end = float(shot["end_seconds"])
    else:
        end = start + float(shot.get("duration_us", 0)) / 1_000_000
    return start, end


def evenly_sample(items: list[dict], count: int) -> list[dict]:
    if len(items) <= count:
        return items
    last = len(items) - 1
    indexes = sorted({round(index * last / (count - 1)) for index in range(count)})
    return [items[index] for index in indexes]


def extract_gray_frame(ffmpeg: Path, source: Path, timestamp: float) -> bytes:
    command = [
        str(ffmpeg),
        "-hide_banner",
        "-loglevel",
        "error",
        "-ss",
        f"{timestamp:.6f}",
        "-i",
        str(source),
        "-frames:v",
        "1",
        "-vf",
        f"scale={FRAME_WIDTH}:180:flags=bilinear,crop={FRAME_WIDTH}:{FRAME_HEIGHT}:0:0,format=gray",
        "-f",
        "rawvideo",
        "pipe:1",
    ]
    process = subprocess.run(command, capture_output=True)
    if process.returncode:
        raise RuntimeError(process.stderr.decode("utf-8", errors="replace"))
    expected = FRAME_WIDTH * FRAME_HEIGHT
    if len(process.stdout) != expected:
        raise RuntimeError(
            f"Unexpected extracted frame size at {timestamp:.3f}s: "
            f"{len(process.stdout)} != {expected}"
        )
    return process.stdout


def normalized_mean_absolute_difference(first: bytes, second: bytes) -> float:
    difference = sum(abs(a - b) for a, b in zip(first, second))
    return difference / (len(first) * 255.0)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("project_dir", type=Path)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--recipe", type=Path)
    parser.add_argument("--ffmpeg", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--sample-count", type=int, default=12)
    parser.add_argument("--minimum-frame-difference", type=float, default=0.012)
    parser.add_argument("--smoothness-sample-points", type=int, default=9)
    parser.add_argument("--maximum-jitter-spike-ratio", type=float, default=3.5)
    args = parser.parse_args()

    project = args.project_dir.resolve()
    work = project / "work"
    source = (args.source or work / "remix.mp4").resolve()
    recipe_path = (args.recipe or work / "recipe.json").resolve()
    output = (args.output or work / "body_motion_validation.json").resolve()
    ffmpeg = args.ffmpeg.resolve()
    if not source.is_file() or not recipe_path.is_file() or not ffmpeg.is_file():
        raise FileNotFoundError(
            f"Missing source, recipe, or FFmpeg: {source}, {recipe_path}, {ffmpeg}"
        )

    recipe = json.loads(recipe_path.read_text(encoding="utf-8"))
    body_shots = [
        shot for shot in recipe.get("shots", []) if BODY_SHOT.fullmatch(str(shot.get("id", "")))
    ]
    parameter_failures = []
    for shot in body_shots:
        motion = shot.get("motion", {})
        start_scale = float(motion.get("scale_start", 0.0))
        end_scale = float(motion.get("scale_end", 0.0))
        focus_x = motion.get("focus_x")
        focus_y = motion.get("focus_y")
        reasons = []
        if motion.get("type") != "push_to_subject":
            reasons.append("motion type is not push_to_subject")
        if motion.get("easing") != "smoothstep":
            reasons.append("easing is not smoothstep")
        if int(motion.get("oversample_factor", 0)) < 3:
            reasons.append("oversample_factor is below 3")
        if motion.get("frame_interpolation") != "continuous":
            reasons.append("frame_interpolation is not continuous")
        if end_scale - start_scale < 0.075:
            reasons.append("scale increase is below 7.5%")
        if end_scale - start_scale > 0.14:
            reasons.append("scale increase exceeds 14%")
        if not isinstance(focus_x, (int, float)) or not 0.0 <= float(focus_x) <= 1.0:
            reasons.append("focus_x is missing or outside 0..1")
        if not isinstance(focus_y, (int, float)) or not 0.0 <= float(focus_y) <= 1.0:
            reasons.append("focus_y is missing or outside 0..1")
        if reasons:
            parameter_failures.append({"shot_id": shot.get("id"), "reasons": reasons})

    candidates = [
        shot for shot in body_shots if shot_times(shot)[1] - shot_times(shot)[0] >= 1.0
    ]
    samples = evenly_sample(candidates, max(2, args.sample_count)) if candidates else []
    rendered_samples = []
    for shot in samples:
        start, end = shot_times(shot)
        duration = end - start
        point_count = max(5, args.smoothness_sample_points)
        times = [start + duration * (0.15 + 0.70 * index / (point_count - 1)) for index in range(point_count)]
        frames = [extract_gray_frame(ffmpeg, source, timestamp) for timestamp in times]
        adjacent = [normalized_mean_absolute_difference(frames[index], frames[index + 1]) for index in range(len(frames) - 1)]
        first, second = frames[0], frames[-1]
        score = normalized_mean_absolute_difference(first, second)
        median_step = statistics.median(adjacent) if adjacent else 0.0
        maximum_step = max(adjacent, default=0.0)
        jitter_spike_ratio = maximum_step / max(median_step, 1e-9)
        smooth = bool(adjacent) and jitter_spike_ratio <= args.maximum_jitter_spike_ratio
        rendered_samples.append(
            {
                "shot_id": shot["id"],
                "first_time": round(times[0], 6),
                "second_time": round(times[-1], 6),
                "normalized_frame_difference": round(score, 6),
                "movement_detected": score >= args.minimum_frame_difference,
                "adjacent_frame_differences": [round(value, 6) for value in adjacent],
                "jitter_spike_ratio": round(jitter_spike_ratio, 4),
                "smooth_motion_detected": smooth,
            }
        )

    checks = {
        "body_shots_exist": bool(body_shots),
        "all_body_shots_have_subject_motion_parameters": not parameter_failures,
        "rendered_motion_samples_exist": bool(rendered_samples),
        "all_rendered_motion_samples_move": bool(rendered_samples)
        and all(item["movement_detected"] for item in rendered_samples),
        "all_rendered_motion_samples_are_smooth": bool(rendered_samples)
        and all(item["smooth_motion_detected"] for item in rendered_samples),
    }
    report = {
        "passed": all(checks.values()),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source": str(source),
        "source_sha256": sha256(source),
        "recipe": str(recipe_path),
        "recipe_sha256": sha256(recipe_path),
        "minimum_frame_difference": args.minimum_frame_difference,
        "maximum_jitter_spike_ratio": args.maximum_jitter_spike_ratio,
        "body_shot_count": len(body_shots),
        "sample_count": len(rendered_samples),
        "checks": checks,
        "parameter_failures": parameter_failures,
        "rendered_samples": rendered_samples,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
