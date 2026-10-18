#!/usr/bin/env python3
"""Validate that every storyboard shot uses a unique image and survives in the final video."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path


BODY_ID = re.compile(r"^S\d{3,}$")
WIDTH = 256
HEIGHT = 144


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def decode_check(ffmpeg: Path, source: Path) -> tuple[bool, str]:
    process = subprocess.run(
        [str(ffmpeg), "-v", "error", "-i", str(source), "-map", "0:v:0", "-f", "null", "-"],
        capture_output=True,
    )
    return process.returncode == 0, process.stderr.decode("utf-8", errors="replace")


def frame(ffmpeg: Path, source: Path, timestamp: float) -> bytes:
    process = subprocess.run(
        [
            str(ffmpeg), "-v", "error", "-ss", f"{timestamp:.6f}", "-i", str(source),
            "-frames:v", "1", "-vf", f"scale={WIDTH}:{HEIGHT}:flags=bilinear,format=rgb24",
            "-f", "rawvideo", "pipe:1",
        ],
        capture_output=True,
    )
    if process.returncode or len(process.stdout) != WIDTH * HEIGHT * 3:
        raise RuntimeError(process.stderr.decode("utf-8", errors="replace"))
    return process.stdout


def difference(first: bytes, second: bytes) -> float:
    return sum(abs(a - b) for a, b in zip(first, second)) / (len(first) * 255.0)


def storyboard_ids(path: Path) -> list[str]:
    ids = []
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        parts = [item.strip() for item in line.strip().strip("|").split("|")]
        if parts and BODY_ID.fullmatch(parts[0]):
            ids.append(parts[0])
    return ids


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("project_dir", type=Path)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--recipe", type=Path)
    parser.add_argument("--ffmpeg", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--minimum-shot-difference", type=float, default=0.004)
    parser.add_argument("--maximum-frozen-transitions", type=int, default=2)
    args = parser.parse_args()

    project = args.project_dir.resolve()
    work = project / "work"
    source = (args.source or work / "remix.mp4").resolve()
    recipe_path = (args.recipe or work / "recipe.json").resolve()
    storyboard = project / "03_分镜表.md"
    output = (args.output or work / "shot_sequence_validation.json").resolve()
    ffmpeg = args.ffmpeg.resolve()
    for path in (source, recipe_path, storyboard, ffmpeg):
        if not path.is_file():
            raise FileNotFoundError(path)

    recipe = json.loads(recipe_path.read_text(encoding="utf-8-sig"))
    shots = [shot for shot in recipe.get("shots", []) if BODY_ID.fullmatch(str(shot.get("id", "")))]
    expected_ids = storyboard_ids(storyboard)
    actual_ids = [str(shot.get("id")) for shot in shots]
    image_failures = []
    image_hashes: dict[str, str] = {}
    for shot in shots:
        shot_id = str(shot["id"])
        image = Path(str(shot.get("image_path", "")))
        if not image.is_file():
            image_failures.append({"shot_id": shot_id, "reason": "missing_image", "path": str(image)})
            continue
        digest = sha256(image)
        if digest in image_hashes:
            image_failures.append({"shot_id": shot_id, "reason": "duplicate_image_content", "same_as": image_hashes[digest], "path": str(image)})
        else:
            image_hashes[digest] = shot_id

    decoded, decode_error = decode_check(ffmpeg, source)
    midpoints = []
    for shot in shots:
        start = float(shot.get("start_seconds", 0.0))
        end = float(shot.get("end_seconds", start + float(shot.get("duration_us", 0)) / 1_000_000))
        midpoints.append({"shot_id": str(shot["id"]), "time": start + max(0.02, end - start) * 0.5})

    transitions = []
    previous = None
    frozen_run = 0
    longest_frozen_run = 0
    for item in midpoints:
        current = frame(ffmpeg, source, float(item["time"]))
        if previous is not None:
            score = difference(previous, current)
            frozen = score < args.minimum_shot_difference
            frozen_run = frozen_run + 1 if frozen else 0
            longest_frozen_run = max(longest_frozen_run, frozen_run)
            transitions.append({"to_shot": item["shot_id"], "difference": round(score, 6), "near_frozen": frozen})
        previous = current

    checks = {
        "final_video_decodes_without_error": decoded,
        "recipe_ids_match_storyboard": actual_ids == expected_ids and bool(actual_ids),
        "every_body_shot_has_an_existing_unique_image": not image_failures and len(image_hashes) == len(shots),
        "final_video_has_no_long_frozen_run": longest_frozen_run <= args.maximum_frozen_transitions,
    }
    report = {
        "passed": all(checks.values()),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source": str(source),
        "source_sha256": sha256(source),
        "recipe": str(recipe_path),
        "recipe_sha256": sha256(recipe_path),
        "storyboard": str(storyboard),
        "storyboard_sha256": sha256(storyboard),
        "body_shot_count": len(shots),
        "unique_image_count": len(image_hashes),
        "longest_frozen_transition_run": longest_frozen_run,
        "checks": checks,
        "image_failures": image_failures,
        "transitions": transitions,
        "decode_error": decode_error[-2000:] if decode_error else "",
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
