#!/usr/bin/env python3
"""Validate the fixed Markdown storyboard used by life-experience videos."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path


EXPECTED_HEADER = [
    "镜头ID", "旁白原文", "visual_anchor_text", "叙事任务",
    "画面描述（时间/人物/地点/动作/情绪）", "景别与构图", "主体焦点",
    "运镜", "连续性与禁止项", "素材路径", "状态",
]
SHOT_ID_RE = re.compile(r"^(H\d{2}|I\d{2}|S\d{3})$")
COORDINATE_RE = re.compile(r"^`?\[\s*(?:0(?:\.\d+)?|1(?:\.0+)?)\s*,\s*(?:0(?:\.\d+)?|1(?:\.0+)?)\s*\]`?$")


def cells(line: str) -> list[str]:
    return [item.strip() for item in line.strip().strip("|").split("|")]


def normalize(value: str) -> str:
    return re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]", "", value)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def unfinished(value: str) -> bool:
    value = value.strip()
    if not value or value == "待填写":
        return True
    if value.startswith("[") or value.startswith("`["):
        return not bool(COORDINATE_RE.fullmatch(value))
    return False


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("storyboard", type=Path)
    parser.add_argument("--project-dir", type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()

    project = (args.project_dir or args.storyboard.parent).resolve()
    storyboard = args.storyboard.resolve()
    failures: list[str] = []
    if storyboard.name != "03_分镜表.md":
        failures.append("分镜文件名必须为 03_分镜表.md")
    text = storyboard.read_text(encoding="utf-8-sig")
    for heading in ["## A. 项目信息", "## B. 角色与连续性锁定", "## C. 开头分镜", "## D. 正文分镜", "## E. 生图统一提示词", "## F. 制作统计与验收"]:
        if heading not in text:
            failures.append(f"缺少固定章节：{heading}")

    rows: list[dict[str, str]] = []
    active_header: list[str] | None = None
    for line in text.splitlines():
        row = cells(line) if line.lstrip().startswith("|") else []
        if row == EXPECTED_HEADER:
            active_header = row
            continue
        if active_header and len(row) == len(EXPECTED_HEADER) and SHOT_ID_RE.fullmatch(row[0]):
            rows.append(dict(zip(EXPECTED_HEADER, row)))

    ids = [row["镜头ID"] for row in rows]
    if len(ids) != len(set(ids)):
        failures.append("存在重复镜头ID")
    if [item for item in ids if item.startswith("H")] != ["H01", "H02"]:
        failures.append("冷开场镜头必须且只能为 H01—H02")
    if [item for item in ids if item.startswith("I")] != ["I01", "I02", "I03", "I04", "I10"]:
        failures.append("品牌片头镜头必须且只能为 I01—I04、I10")
    body_ids = [item for item in ids if item.startswith("S")]
    expected_body = [f"S{index:03d}" for index in range(1, len(body_ids) + 1)]
    if body_ids != expected_body:
        failures.append("正文镜头必须从 S001 开始连续编号")
    if len(body_ids) < 2:
        failures.append("正文分镜至少需要两个镜头")

    manuscript_path = project / "01_确认文稿.md"
    manuscript = normalize(manuscript_path.read_text(encoding="utf-8-sig")) if manuscript_path.is_file() else ""
    for row in rows:
        shot_id = row["镜头ID"]
        for field in EXPECTED_HEADER[1:]:
            value = row[field]
            if unfinished(value):
                failures.append(f"{shot_id} 的 {field} 未填写完整")
        if shot_id.startswith(("H", "S")):
            narration = normalize(row["旁白原文"])
            anchor = normalize(row["visual_anchor_text"])
            if manuscript and narration and narration not in manuscript:
                failures.append(f"{shot_id} 的旁白原文不在确认文稿中")
            if manuscript and anchor and anchor not in manuscript:
                failures.append(f"{shot_id} 的 visual_anchor_text 不在确认文稿中")
        if "无文字" not in row["连续性与禁止项"] and "禁止文字" not in row["连续性与禁止项"]:
            failures.append(f"{shot_id} 未明确禁止画面文字")

    config_path = project / "00_项目配置.json"
    if config_path.is_file():
        config = json.loads(config_path.read_text(encoding="utf-8-sig"))
        title = str(config.get("title", "")).strip()
        if title and title not in text:
            failures.append("分镜标题与 00_项目配置.json 不一致")

    report = {
        "storyboard": str(storyboard),
        "storyboard_sha256": sha256(storyboard),
        "passed": not failures,
        "shot_counts": {"cold_hook": sum(x.startswith("H") for x in ids), "brand_intro": sum(x.startswith("I") for x in ids), "body": len(body_ids)},
        "failures": failures,
    }
    out = (args.out or project / "work" / "storyboard_validation.json").resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
