#!/usr/bin/env python3
"""Validate that the distributed Skill is self-contained and the host can run it."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import shutil
import sys
from pathlib import Path

sys.dont_write_bytecode = True

from font_utils import resolve_font


SKILL_ROOT = Path(__file__).resolve().parent.parent
REQUIRED_FILES = [
    "scripts/cover_specs.py", "references/covers.md",
    "assets/visual-style.json", "assets/nine-grid-intro/motion-spec.json",
    "scripts/visual_style.py", "scripts/init_episode.py", "scripts/final_media.py", "references/commands.md",
    "SKILL.md",
    "agents/openai.yaml",
    "scripts/validate_audio_input.py",
    "references/audio-input.md",
    "scripts/check_public_release.py",
    "assets/intro-plan-template.json",
    "assets/storyboard-template.md",
    "assets/image-review-template.md",
    "assets/image-repair-directives-template.json",
    "assets/final-av-review-template.json",
    "assets/chatgpt-f12-batch-template.js",
    "assets/chatgpt-f12-template-lock.json",
    "assets/gemini-f12-batch-template.js",
    "assets/nine-grid-intro/NineGridIntro.tsx",
    "assets/two-shot-cold-hook/TwoShotColdHook.tsx",
    "assets/two-shot-cold-hook/OpeningSequence.tsx",
    "assets/two-shot-cold-hook/cold-hook-config.json",
    "assets/remotion-package-template.json",
    "references/intro-template.md",
    "references/runtime.md",
    "references/execution-protocol.md",
    "references/delivery.md",
    "references/incremental-execution.md",
    "references/quality-review.md",
    "references/jianying-draft.md",
    "scripts/production_workflow.py",
    "scripts/validation_cache.py",
    "scripts/narration_alignment.py",
    "scripts/validate_image_review.py",
    "scripts/local_repair.py",
    "scripts/prepare_nine_grid_intro.py",
    "scripts/build_chatgpt_f12_script.py",
    "scripts/build_gemini_f12_script.py",
    "scripts/image_prompt_compiler.py",
    "scripts/audit_image_set.py",
    "scripts/caption_utils.py",
    "scripts/enforce_single_line_captions.py",
    "scripts/build_cover_variants.py",
    "scripts/validate_storyboard_md.py",
    "scripts/validate_shot_sequence.py",
    "scripts/validate_caption_render.py",
    "scripts/compose_audio_mix.py",
    "scripts/validate_final_delivery.py",
    "scripts/publish_preview.py",
]
PROJECT_PATH_PATTERN = re.compile(r"(?i)[A-Z]:[/\\](?:Users[/\\]|Python[/\\]|Voice|Agent|life-experience)")
PYTHON_MODULES = {
    "PIL": "Pillow",
    "numpy": "numpy",
    "faster_whisper": "faster-whisper",
    "opencc": "opencc-python-reimplemented",
}


def add(checks: list[dict], name: str, ok: bool, detail: str, required: bool = True) -> None:
    checks.append({"name": name, "ok": ok, "required": required, "detail": detail})


def static_checks(checks: list[dict], strict=True) -> None:
    for relative in REQUIRED_FILES:
        target = SKILL_ROOT / relative
        add(checks, f"file:{relative}", target.is_file(), str(target))

    caches = sorted(
        str(path.relative_to(SKILL_ROOT))
        for path in SKILL_ROOT.rglob("*")
        if path.name == "__pycache__" or path.suffix == ".pyc"
    )
    add(checks, "generated-caches", not caches, ", ".join(caches) if caches else "none", required=strict)

    leaked_paths: list[str] = []
    for path in SKILL_ROOT.rglob("*"):
        if set(path.relative_to(SKILL_ROOT).parts) & {'.git', '.venv', 'node_modules'}:
            continue
        if not path.is_file() or path.suffix.lower() not in {".md", ".json", ".yaml", ".yml", ".py", ".ts", ".tsx"}:
            continue
        text = path.read_text(encoding="utf-8-sig", errors="replace")
        if PROJECT_PATH_PATTERN.search(text):
            leaked_paths.append(str(path.relative_to(SKILL_ROOT)))
    add(checks, "machine-specific-paths", not leaked_paths, ", ".join(leaked_paths) if leaked_paths else "none")

    template = json.loads((SKILL_ROOT / "assets" / "intro-plan-template.json").read_text(encoding="utf-8"))
    intro = template.get("intro", {})
    locked = intro.get("preview_layer_count") == 4 and intro.get("preview_source_starts") == [0, 27, 54, 81]
    add(checks, "locked-intro-4-layers", locked, json.dumps({
        "preview_layer_count": intro.get("preview_layer_count"),
        "preview_source_starts": intro.get("preview_source_starts"),
    }, ensure_ascii=False))


def runtime_checks(checks: list[dict]) -> None:
    for command in ["ffmpeg", "ffprobe", "node", "npx"]:
        resolved = shutil.which(command)
        add(checks, f"command:{command}", bool(resolved), resolved or "not found")
    for module, package in PYTHON_MODULES.items():
        found = importlib.util.find_spec(module) is not None
        add(checks, f"python:{package}", found, "installed" if found else "not installed")
    draft_module = importlib.util.find_spec("pyJianYingDraft") is not None
    add(checks, "python:pyJianYingDraft", draft_module, "installed" if draft_module else "optional; required only for Jianying drafts", required=False)
    for kind in ["bold", "display"]:
        try:
            path = resolve_font(kind)
        except FileNotFoundError as exc:
            add(checks, f"font:{kind}", False, str(exc))
        else:
            add(checks, f"font:{kind}", True, str(path))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--static-only", action="store_true", help="check only distributed files and paths")
    args = parser.parse_args()
    checks: list[dict] = []
    static_checks(checks, strict=args.static_only)
    if not args.static_only:
        runtime_checks(checks)
    failures = [item for item in checks if item["required"] and not item["ok"]]
    report = {
        "skill_root": str(SKILL_ROOT),
        "mode": "static" if args.static_only else "runtime",
        "passed": not failures,
        "checks": checks,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
