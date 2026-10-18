#!/usr/bin/env python3
"""Copy a generated shot into the project and update its manifest record."""

from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--shot", required=True)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--prompt-file", type=Path)
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.source.is_file():
        raise SystemExit(f"Generated source does not exist: {args.source}")
    same_file = args.source.resolve() == args.output.resolve()
    if args.output.exists() and not args.force and not same_file:
        raise SystemExit(f"Output already exists: {args.output}")

    data = json.loads(args.manifest.read_text(encoding="utf-8"))
    record = next((item for item in data["shots"] if item["id"] == args.shot), None)
    if record is None:
        raise SystemExit(f"Unknown shot id: {args.shot}")

    with Image.open(args.source) as image:
        width, height = image.size
    ratio = width / height
    if abs(ratio - 16 / 9) > 0.015:
        raise SystemExit(
            f"Image ratio {width}x{height} ({ratio:.4f}) is not close enough to 16:9"
        )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    if not same_file:
        shutil.copy2(args.source, args.output)
    record.update(
        {
            "status": "complete",
            "image_path": str(args.output.resolve()),
            "width": width,
            "height": height,
            "ratio": round(ratio, 6),
            "prompt": args.prompt_file.read_text(encoding="utf-8")
            if args.prompt_file
            else record.get("prompt"),
            "last_error": None,
            "completed_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    args.manifest.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"Recorded {args.shot}: {width}x{height} -> {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
