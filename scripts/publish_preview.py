#!/usr/bin/env python3
"""Publish the latest video, optionally with a self-contained Jianying draft."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from PIL import Image
from cover_specs import COVER_SIZES


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require_delivery_validation(project: Path, source: Path) -> Path:
    # Re-evaluate the current files immediately before publication. A previously
    # approved report is not permission to publish changed covers/dependencies.
    fresh = subprocess.run([sys.executable, '-B', str(Path(__file__).with_name('validate_final_delivery.py')),
                            str(project), '--source', str(source)],
                           capture_output=True, text=True, encoding='utf-8', errors='replace')
    if fresh.returncode:
        raise RuntimeError('当前交付证据已失效或未通过，请修复后重新校验：' +
                           (fresh.stderr or fresh.stdout)[-2000:])
    validation_path = project / "work" / "delivery_validation.json"
    if not validation_path.is_file():
        raise RuntimeError("最终发布前必须先运行 validate_final_delivery.py")
    validation = json.loads(validation_path.read_text(encoding="utf-8"))
    if validation.get("passed") is not True:
        raise RuntimeError("最终交付校验未通过")
    if validation.get("source_sha256") != sha256(source):
        raise RuntimeError("当前视频与交付校验哈希不一致；请重新渲染并校验")
    if validation_path.stat().st_mtime + 1e-3 < source.stat().st_mtime:
        raise RuntimeError("交付校验早于当前视频；请重新校验")
    checks = validation.get("checks", {})
    for ratio in COVER_SIZES:
        if checks.get(f"cover_{ratio}_exists_and_has_expected_size") is not True:
            raise RuntimeError(f"缺少合格的最终封面：封面_{ratio}.jpg")
    expected = {project / "最终成片" / f"封面_{ratio}.jpg": size for ratio, size in COVER_SIZES.items()}
    for cover, size in expected.items():
        if not cover.is_file():
            raise RuntimeError(f"最终发布缺少封面：{cover}")
        try:
            with Image.open(cover) as image:
                if image.size != size:
                    raise RuntimeError(f"封面尺寸错误：{cover}，应为 {size[0]}×{size[1]}")
        except OSError as exc:
            raise RuntimeError(f"封面无法读取：{cover}") from exc
    return validation_path


def default_title(project: Path) -> str:
    script = project / "01_确认文稿.md"
    if script.is_file():
        for line in script.read_text(encoding="utf-8").splitlines():
            if line.startswith("# ") and line[2:].strip():
                return line[2:].strip()
    return project.name


def safe_filename(value: str) -> str:
    value = re.sub(r'[<>:"/\\|?*]', "_", value).strip().rstrip(".")
    return value or "最终成片"


def replace_strings(value: Any, old: str, new: str) -> Any:
    if isinstance(value, str):
        return value.replace(old, new)
    if isinstance(value, list):
        return [replace_strings(item, old, new) for item in value]
    if isinstance(value, dict):
        return {key: replace_strings(item, old, new) for key, item in value.items()}
    return value


def rewrite_json_roots(root: Path, old: str, new: str) -> None:
    for path in root.rglob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        data = replace_strings(data, old, new)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def publish_draft(project: Path, destination_dir: Path) -> tuple[Path, list[str]]:
    source = project / "work" / "jianying_draft"
    if not source.is_dir():
        raise FileNotFoundError(source)

    destination = destination_dir / "剪映草稿"
    pending = destination_dir / ".剪映草稿.pending"
    if pending.exists():
        shutil.rmtree(pending)
    shutil.copytree(source, pending)
    rewrite_json_roots(pending, str(source.resolve()), str(pending.resolve()))

    if destination.exists():
        archive_root = project / "work" / "archive"
        archive_root.mkdir(parents=True, exist_ok=True)
        archived = archive_root / "published_draft_previous"
        if archived.exists():
            if archived.resolve().parent != archive_root.resolve():
                raise RuntimeError("草稿回退目录越出 work/archive")
            shutil.rmtree(archived)
        destination.replace(archived)
    pending_root = str(pending.resolve())
    pending.replace(destination)
    rewrite_json_roots(destination, pending_root, str(destination.resolve()))

    content = json.loads((destination / "draft_content.json").read_text(encoding="utf-8"))
    missing: list[str] = []
    for items in content.get("materials", {}).values():
        if not isinstance(items, list):
            continue
        for item in items:
            material_path = item.get("path") if isinstance(item, dict) else None
            if material_path and not Path(material_path).is_file():
                missing.append(material_path)
    return destination, missing


def archive_internal_delivery_extras(project: Path, destination_dir: Path) -> list[str]:
    """最终成片目录只保留正式交付物；SRT、缩略图和封面底图回收到 work。"""
    extras = []
    for path in (destination_dir.iterdir() if destination_dir.is_dir() else []):
        if not path.is_file():
            continue
        name = path.name.lower()
        if path.suffix.lower() == ".srt" or "缩略图" in path.name or "底图" in path.name or "thumbnail" in name:
            extras.append(path)
    if not extras:
        return []
    archive = project / "work" / "archive" / "delivery_extras_previous"
    archive.mkdir(parents=True, exist_ok=True)
    moved = []
    for path in extras:
        target = archive / path.name
        if target.exists():
            target.unlink()
        path.replace(target)
        moved.append(str(target))
    return moved


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("project_dir", type=Path)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--title")
    parser.add_argument("--label", choices=("final", "preview"), default="final")
    parser.add_argument(
        "--include-draft",
        action="store_true",
        help="Publish a self-contained Jianying draft; omitted by default.",
    )
    args = parser.parse_args()

    project = args.project_dir.resolve()
    source = (args.source or (project / "work" / "remix.mp4")).resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    delivery_validation = require_delivery_validation(project, source) if args.label == "final" else None

    title = safe_filename(args.title or default_title(project))
    suffix = "_审核预览" if args.label == "preview" else ""
    destination_dir = project / "最终成片"
    destination_dir.mkdir(parents=True, exist_ok=True)
    archived_extras = archive_internal_delivery_extras(project, destination_dir) if args.label == "final" else []
    destination = destination_dir / f"{title}{suffix}.mp4"
    temporary = destination.with_suffix(".mp4.pending")
    # A reviewer may still have the published MP4 open on Windows. If the
    # destination already matches the validated source byte-for-byte, treat it
    # as published instead of attempting an unnecessary locked-file replace.
    if not (destination.is_file() and sha256(destination) == sha256(source)):
        shutil.copy2(source, temporary)
        temporary.replace(destination)
    elif temporary.exists():
        temporary.unlink()

    draft_output = None
    missing_materials: list[str] = []
    if args.label == "final" and args.include_draft:
        draft_output, missing_materials = publish_draft(project, destination_dir)
        if missing_materials:
            raise RuntimeError(f"Published draft has missing materials: {missing_materials}")

    print(json.dumps({
        "source": str(source),
        "output": str(destination.resolve()),
        "draft_output": str(draft_output.resolve()) if draft_output else None,
        "missing_draft_materials": missing_materials,
        "label": args.label,
        "delivery_validation": str(delivery_validation) if delivery_validation else None,
        "bytes": destination.stat().st_size,
        "archived_internal_extras": archived_extras,
    }, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
