#!/usr/bin/env python3
"""对单期全部分镜图片做技术审核，并产出人工复核与返工候选清单。"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image, ImageFilter, ImageStat


SHOT_ID_RE = re.compile(r"^(?:H\d{2}|I\d{2}|S\d{3})$")


def parse_row(line: str) -> list[str]:
    text = line.strip()
    if not (text.startswith("|") and text.endswith("|")):
        return []
    return [cell.strip() for cell in text[1:-1].split("|")]


def expected_images(storyboard: Path) -> list[dict]:
    rows: list[dict] = []
    for line in storyboard.read_text(encoding="utf-8-sig").splitlines():
        cells = parse_row(line)
        if len(cells) == 11 and SHOT_ID_RE.fullmatch(cells[0]):
            rows.append({"id": cells[0], "path": cells[9].strip("`")})
    if not rows:
        raise ValueError("03_分镜表.md 中没有可识别的 H/I/S 镜头。")
    return rows


def dhash(image: Image.Image, size: int = 16) -> int:
    gray = image.convert("L").resize((size + 1, size), Image.Resampling.LANCZOS)
    getter = getattr(gray, "get_flattened_data", gray.getdata)
    pixels = list(getter())
    result = 0
    for y in range(size):
        row = y * (size + 1)
        for x in range(size):
            result = (result << 1) | int(pixels[row + x] > pixels[row + x + 1])
    return result


def hamming(a: int, b: int) -> int:
    return (a ^ b).bit_count()


def entropy(image: Image.Image) -> float:
    histogram = image.convert("L").histogram()
    total = sum(histogram) or 1
    return -sum((count / total) * math.log2(count / total) for count in histogram if count)


def edge_mean(image: Image.Image) -> float:
    preview = image.convert("L").resize((384, 216), Image.Resampling.LANCZOS)
    return float(ImageStat.Stat(preview.filter(ImageFilter.FIND_EDGES)).mean[0])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project_dir", type=Path)
    parser.add_argument("--min-width", type=int, default=1920)
    parser.add_argument("--min-height", type=int, default=1080)
    parser.add_argument("--near-duplicate-distance", type=int, default=10)
    args = parser.parse_args()

    project = args.project_dir.resolve()
    storyboard = project / "03_分镜表.md"
    rows = expected_images(storyboard)
    report_rows: list[dict] = []
    decoded: list[dict] = []
    repair_ids: set[str] = set()
    review_ids: set[str] = set()

    for row in rows:
        path = project / Path(row["path"].replace("/", "\\"))
        record = {"id": row["id"], "path": str(path), "status": "pass", "failures": [], "warnings": []}
        if not path.is_file():
            record["status"] = "fail"
            record["failures"].append("missing_file")
            repair_ids.add(row["id"])
            report_rows.append(record)
            continue
        try:
            raw = path.read_bytes()
            with Image.open(path) as opened:
                opened.verify()
            with Image.open(path) as opened:
                image = opened.convert("RGB")
                width, height = image.size
                record.update({
                    "width": width,
                    "height": height,
                    "aspect_ratio": round(width / height, 6),
                    "sha256": hashlib.sha256(raw).hexdigest(),
                    "dhash_256": f"{dhash(image):064x}",
                    "entropy": round(entropy(image), 3),
                    "edge_mean": round(edge_mean(image), 3),
                })
                if abs(width / height - 16 / 9) > 0.015:
                    record["failures"].append("not_16_9")
                if width < args.min_width or height < args.min_height:
                    record["failures"].append("resolution_too_small")
                if record["entropy"] < 4.2 or record["edge_mean"] < 6.0:
                    record["warnings"].append("possibly_flat_or_empty; manual richness review required")
                    review_ids.add(row["id"])
                decoded.append({"record": record, "dhash": int(record["dhash_256"], 16)})
        except Exception as exc:  # noqa: BLE001
            record["failures"].append(f"decode_error: {exc}")

        if record["failures"]:
            record["status"] = "fail"
            repair_ids.add(row["id"])
        elif record["warnings"]:
            record["status"] = "manual_review"
        report_rows.append(record)

    by_sha: dict[str, list[dict]] = {}
    for item in decoded:
        by_sha.setdefault(item["record"]["sha256"], []).append(item)
    for group in by_sha.values():
        if len(group) > 1:
            ids = [item["record"]["id"] for item in group]
            for item in group:
                item["record"]["status"] = "fail"
                item["record"]["failures"].append("exact_duplicate_with: " + ", ".join(i for i in ids if i != item["record"]["id"]))
                repair_ids.add(item["record"]["id"])

    near_pairs: list[dict] = []
    for left, right in zip(decoded, decoded[1:]):
        distance = hamming(left["dhash"], right["dhash"])
        if distance <= args.near_duplicate_distance:
            pair = {"left": left["record"]["id"], "right": right["record"]["id"], "dhash_distance": distance}
            near_pairs.append(pair)
            for item in (left, right):
                item["record"]["warnings"].append(f"adjacent_near_duplicate; distance={distance}")
                if item["record"]["status"] == "pass":
                    item["record"]["status"] = "manual_review"
                review_ids.add(item["record"]["id"])

    work = project / "work"
    work.mkdir(parents=True, exist_ok=True)
    report_path = work / "image_set_audit.json"
    repair_path = work / "image_repair_ids.txt"
    review_path = work / "image_manual_review_ids.txt"
    payload = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "project": str(project),
        "expected_count": len(rows),
        "decoded_count": len(decoded),
        "technical_pass": not repair_ids,
        "manual_semantic_review_required": True,
        "repair_ids": sorted(repair_ids),
        "manual_review_ids": sorted(review_ids),
        "adjacent_near_duplicate_pairs": near_pairs,
        "shots": report_rows,
    }
    report_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    repair_path.write_text("\n".join(sorted(repair_ids)) + ("\n" if repair_ids else ""), encoding="utf-8")
    review_path.write_text("\n".join(sorted(review_ids)) + ("\n" if review_ids else ""), encoding="utf-8")
    print(json.dumps({"report": str(report_path), "technical_pass": not repair_ids, "repair_ids": sorted(repair_ids), "manual_review_ids": sorted(review_ids)}, ensure_ascii=False, indent=2))
    return 0 if not repair_ids else 2


if __name__ == "__main__":
    raise SystemExit(main())
