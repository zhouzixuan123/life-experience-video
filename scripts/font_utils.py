#!/usr/bin/env python3
"""Resolve Chinese fonts without assuming one operating system or install path."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parent.parent
FONT_ROOT = SKILL_ROOT / "assets" / "fonts"

FONT_ENV = {
    "bold": "LIFE_EXPERIENCE_FONT_BOLD",
    "display": "LIFE_EXPERIENCE_FONT_DISPLAY",
}

FONT_CANDIDATES = {
    "bold": [
        FONT_ROOT / "NotoSansCJKsc-Bold.otf",
        FONT_ROOT / "SourceHanSansSC-Bold.otf",
        Path("C:/Windows/Fonts/msyhbd.ttc"),
        Path("C:/Windows/Fonts/msyh.ttc"),
        Path("/System/Library/Fonts/PingFang.ttc"),
        Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"),
        Path("/usr/share/fonts/opentype/source-han-sans/SourceHanSansSC-Bold.otf"),
    ],
    "display": [
        FONT_ROOT / "NotoSerifCJKsc-Bold.otf",
        FONT_ROOT / "SourceHanSerifSC-Bold.otf",
        Path("C:/Windows/Fonts/simkai.ttf"),
        Path("C:/Windows/Fonts/msyhbd.ttc"),
        Path("/System/Library/Fonts/STHeiti Medium.ttc"),
        Path("/usr/share/fonts/opentype/noto/NotoSerifCJK-Bold.ttc"),
        Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"),
    ],
}


@lru_cache(maxsize=None)
def resolve_font(kind: str) -> Path:
    if kind not in FONT_CANDIDATES:
        raise ValueError(f"Unknown font kind: {kind}")
    override = os.environ.get(FONT_ENV[kind])
    candidates = [Path(override).expanduser()] if override else []
    candidates.extend(FONT_CANDIDATES[kind])
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    raise FileNotFoundError(
        f"No Chinese {kind} font found. Set {FONT_ENV[kind]} or place an approved font in {FONT_ROOT}."
    )
