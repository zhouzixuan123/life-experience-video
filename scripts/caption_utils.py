#!/usr/bin/env python3
"""中文单行字幕的语义切分与显示宽度工具。"""

from __future__ import annotations

import re
import unicodedata


STRONG_PUNCTUATION = "。！？!?"
MEDIUM_PUNCTUATION = "，,；;：:、"
BAD_LEFT_ENDINGS = tuple("的地得把被在从向给与和或而但及于对将让使比")
BAD_RIGHT_STARTS = (
    "的", "地", "得", "了", "着", "过", "吗", "呢", "吧", "啊", "呀", "而且", "以及",
    "但是", "所以", "如果", "因为", "虽然", "却", "才", "就", "也", "又", "还", "都", "并",
    "仍", "再", "更", "最", "很", "正", "将", "可", "不", "没",
    "里", "上", "下", "中", "内", "外", "前", "后", "量", "钱", "家", "人", "事", "亲",
)
GOOD_RIGHT_STARTS = (
    "但是", "不过", "然而", "所以", "于是", "后来", "直到", "为了", "因为", "如果", "虽然",
    "即使", "与此同时", "第二天", "第二年", "一个月后", "几年后", "从那以后", "可你", "而你",
    "在", "从", "向", "靠", "通过", "当你", "你却", "他却", "她却", "父亲", "母亲", "爸爸", "妈妈",
)


def clean_caption_text(text: str) -> str:
    return "".join(char for char in text if not unicodedata.category(char).startswith("P") and not char.isspace())


def display_units(text: str) -> float:
    units = 0.0
    for char in clean_caption_text(text):
        if ord(char) < 128:
            units += 0.55 if char.isalnum() else 0.35
        else:
            units += 1.0
    return units


def _strong_sentences(text: str) -> list[str]:
    chunks = re.findall(rf"[^ {re.escape(STRONG_PUNCTUATION)}]+[{re.escape(STRONG_PUNCTUATION)}]?", text.replace(" ", ""))
    return [chunk for chunk in chunks if clean_caption_text(chunk)] or [text]


def _candidate_score(text: str, index: int, target: float, minimum_units: float) -> float:
    left = clean_caption_text(text[:index])
    right = clean_caption_text(text[index:])
    left_units, right_units = display_units(left), display_units(right)
    if left_units < minimum_units or right_units < 2:
        return -10_000.0
    score = -abs(left_units - target) * 2.0
    previous = text[index - 1] if index else ""
    following = text[index:] if index < len(text) else ""
    if previous in MEDIUM_PUNCTUATION:
        score += 20.0
    if any(following.startswith(word) for word in GOOD_RIGHT_STARTS):
        score += 18.0
    if previous in BAD_LEFT_ENDINGS:
        score -= 30.0
    if any(following.startswith(word) for word in BAD_RIGHT_STARTS):
        score -= 24.0
    if previous.isascii() and following[:1].isascii():
        score -= 12.0
    return score


def _split_long_clause(text: str, max_units: float, minimum_units: float = 5.0) -> list[str]:
    compact = text.strip()
    if display_units(compact) <= max_units:
        cleaned = clean_caption_text(compact)
        return [cleaned] if cleaned else []

    pieces: list[str] = []
    remaining = compact
    while display_units(remaining) > max_units:
        best_index, best_score = 0, -10_000.0
        for index in range(1, len(remaining)):
            if display_units(remaining[:index]) > max_units:
                break
            score = _candidate_score(remaining, index, max_units * 0.78, minimum_units)
            if score > best_score:
                best_index, best_score = index, score
        if best_index <= 0:
            # 极端无边界文本才按显示单位截断；仍避免把单字甩到下一条。
            for index in range(1, len(remaining) + 1):
                if display_units(remaining[:index]) > max_units:
                    best_index = max(1, index - 1)
                    break
            best_index = best_index or max(1, len(remaining) - 1)
        left = clean_caption_text(remaining[:best_index])
        if left:
            pieces.append(left)
        remaining = remaining[best_index:].lstrip(MEDIUM_PUNCTUATION + STRONG_PUNCTUATION + " ")
    tail = clean_caption_text(remaining)
    if tail:
        if pieces and display_units(tail) < 3 and display_units(pieces[-1] + tail) <= max_units:
            pieces[-1] += tail
        else:
            pieces.append(tail)
    return pieces


def split_caption_text(text: str, max_units: float = 15.0) -> list[str]:
    """短句保持完整；只有确实超宽时才在语义边界拆分。"""
    cleaned = clean_caption_text(text)
    if not cleaned:
        return []
    if display_units(cleaned) <= max_units:
        return [cleaned]
    result: list[str] = []
    for sentence in _strong_sentences(text):
        result.extend(_split_long_clause(sentence, max_units=max_units))
    return result
