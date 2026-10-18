#!/usr/bin/env python3
"""Build a resumable image-generation manifest from a Markdown shot table."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from visual_style import resolve as resolve_style


SHOT_ID_RE = re.compile(r"^(H\d{2}|I\d{2}|S\d{3})$")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--storyboard", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--image-dir", required=True, type=Path)
    parser.add_argument("--reference", action="append", default=[])
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.out.exists() and not args.force:
        raise SystemExit(f"Output already exists: {args.out}")

    text = args.storyboard.read_text(encoding="utf-8")
    rows: list[dict[str, object]] = []
    seen: set[str] = set()
    for line in text.splitlines():
        if not line.lstrip().startswith("|"):
            continue
        parts = [part.strip() for part in line.strip().strip("|").split("|")]
        if not parts or not SHOT_ID_RE.fullmatch(parts[0]):
            continue
        if len(parts) == 11:
            shot_id, narration, anchor, purpose, visual, composition, focus, motion, continuity, asset_path, _status = parts[:11]
        else:
            continue
        if shot_id in seen:
            raise SystemExit(f"Duplicate shot id: {shot_id}")
        seen.add(shot_id)

        planned = Path(asset_path.strip('`'))
        if not planned.is_absolute(): planned = args.storyboard.resolve().parent / planned
        selected = planned.resolve() if planned.is_file() else None
        rows.append(
            {
                "id": shot_id,
                "narration": narration,
                "visual_anchor_text": anchor,
                "purpose": purpose,
                "visual": visual,
                "composition": composition,
                "focus": focus,
                "motion": motion,
                "continuity": continuity,
                "planned_asset_path": asset_path,
                "status": "complete" if selected else "pending",
                "image_path": str(selected) if selected else None,
                "width": None,
                "height": None,
                "ratio": None,
                "prompt": None,
                "last_error": None,
            }
        )

    if not rows:
        raise SystemExit("No storyboard shot rows found")

    body_numbers = [int(str(row["id"])[1:]) for row in rows if str(row["id"]).startswith("S")]
    expected = list(range(1, len(body_numbers) + 1))
    if body_numbers != expected:
        raise SystemExit(f"Body shot sequence is not contiguous: {body_numbers}")

    manifest = {
        "version": 1,
        "project": args.storyboard.resolve().parent.name,
        "aspect_ratio": "16:9",
        "style": resolve_style(args.storyboard.resolve().parent),
        "storyboard": str(args.storyboard.resolve()),
        "image_dir": str(args.image_dir.resolve()),
        "references": [str(Path(item).resolve()) for item in args.reference],
        "total_shots": len(rows),
        "shots": rows,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"Created {args.out} with {len(rows)} shots")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
