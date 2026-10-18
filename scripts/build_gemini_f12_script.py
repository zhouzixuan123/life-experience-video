#!/usr/bin/env python3
"""从单期项目配置和固定分镜表生成 Gemini 网页端 F12 批量生图脚本。"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
from pathlib import Path

from image_prompt_compiler import enrich_shots
from visual_style import resolve as resolve_style


DEFAULT_NEGATIVE = (
    "no readable text, no subtitles, no watermark, no logo, no duplicated protagonist, "
    "no extra limbs, no character age drift, no unrelated characters or locations"
)

SHOT_ID_RE = re.compile(r"^(?:H\d{2}|I\d{2}|S\d{3})$")
ROLE_ID_RE = re.compile(r"^[A-Z]\d{2}$")


def parse_row(line: str) -> list[str]:
    text = line.strip()
    if not (text.startswith("|") and text.endswith("|")):
        return []
    return [cell.strip() for cell in text[1:-1].split("|")]


def code_block_after(text: str, heading: str) -> str:
    pattern = rf"###\s+{re.escape(heading)}\s*\n\s*```(?:text)?\s*\n(.*?)\n```"
    match = re.search(pattern, text, flags=re.DOTALL | re.IGNORECASE)
    return re.sub(r"\s+", " ", match.group(1)).strip() if match else ""


def parse_storyboard(path: Path) -> tuple[list[dict], list[dict], str, str]:
    text = path.read_text(encoding="utf-8-sig")
    shots: list[dict] = []
    roles: list[dict] = []

    for line in text.splitlines():
        cells = parse_row(line)
        if not cells or set(cells[0]) <= {"-", ":"}:
            continue

        if len(cells) == 11 and SHOT_ID_RE.fullmatch(cells[0]):
            shots.append(
                {
                    "id": cells[0],
                    "narration": cells[1],
                    "anchor": cells[2],
                    "task": cells[3],
                    "scene": cells[4],
                    "layout": cells[5],
                    "rules": cells[8],
                    "path": cells[9].strip("`"),
                }
            )
        elif len(cells) == 7 and ROLE_ID_RE.fullmatch(cells[0]):
            roles.append(
                {
                    "id": cells[0],
                    "identity": cells[1],
                    "age": cells[2],
                    "appearance": cells[3],
                    "relation": cells[4],
                    "avoid": cells[5],
                }
            )

    style = code_block_after(text, "正向锚点")
    negative = code_block_after(text, "统一禁止项")
    return shots, roles, style, negative


def validate_shots(shots: list[dict]) -> None:
    ids = [shot["id"] for shot in shots]
    if len(ids) != len(set(ids)):
        raise ValueError("03_分镜表.md 存在重复镜头 ID。")

    required_opening = ["H01", "H02", "I01", "I02", "I03", "I04", "I10"]
    missing_opening = [shot_id for shot_id in required_opening if shot_id not in ids]
    if missing_opening:
        raise ValueError("缺少固定开头镜头：" + ", ".join(missing_opening))

    body = [shot_id for shot_id in ids if shot_id.startswith("S")]
    expected_body = [f"S{index:03d}" for index in range(1, len(body) + 1)]
    if body != expected_body:
        raise ValueError("正文镜头必须从 S001 连续编号，且按编号顺序排列。")

    for shot in shots:
        for key in ("narration", "task", "scene", "layout", "rules"):
            value = shot[key].strip()
            if not value or (value.startswith("[") and value.endswith("]")):
                raise ValueError(f"{shot['id']} 的 {key} 尚未填写。")


def role_prompt(roles: list[dict]) -> str:
    if not roles:
        raise ValueError("03_分镜表.md 的 B.角色与连续性锁定为空。")
    lines = ["Continuity lock dynamically compiled for this project:"]
    for role in roles:
        lines.append(
            f"{role['id']} — identity: {role['identity']}; age/stage: {role['age']}; "
            f"fixed appearance and clothing: {role['appearance']}; relationship/state: {role['relation']}; "
            f"must not drift: {role['avoid']}."
        )
    lines.append("Use only the characters and props required by the current shot; do not import people or locations from other shots.")
    return " ".join(lines)


def parse_ids(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        for item in re.split(r"[,，\s]+", value.strip()):
            if item and item not in result:
                result.append(item)
    invalid = [item for item in result if not SHOT_ID_RE.fullmatch(item)]
    if invalid:
        raise ValueError("无效返工镜头 ID：" + ", ".join(invalid))
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project_dir", type=Path, help="包含 00_项目配置.json 和 03_分镜表.md 的单期目录")
    parser.add_argument("--output", type=Path, help="输出 JS；默认写入单期根目录 Gemini_F12_批量生图.js")
    parser.add_argument("--repair-ids", nargs="*", default=[], help="只补生指定镜头；支持空格或逗号分隔")
    parser.add_argument("--validate-only", action="store_true", help="只校验输入，不写脚本")
    args = parser.parse_args()

    project_dir = args.project_dir.resolve()
    config_path = project_dir / "00_项目配置.json"
    storyboard_path = project_dir / "03_分镜表.md"
    if not config_path.is_file() or not storyboard_path.is_file():
        raise FileNotFoundError("单期目录必须同时包含 00_项目配置.json 和 03_分镜表.md。")

    project_config = json.loads(config_path.read_text(encoding="utf-8-sig"))
    title = str(project_config.get("title", "")).strip()
    if not title:
        raise ValueError("00_项目配置.json 缺少非空 title。")

    shots, roles, style, negative = parse_storyboard(storyboard_path)
    validate_shots(shots)
    repair_ids = parse_ids(args.repair_ids)
    unknown = [shot_id for shot_id in repair_ids if shot_id not in {shot["id"] for shot in shots}]
    if unknown:
        raise ValueError("返工清单包含分镜表中不存在的 ID：" + ", ".join(unknown))
    shots = enrich_shots(shots, project_dir, repair_ids)

    payload = {
        "schema_version": 1,
        "title": title,
        "revision": project_config.get("revision"),
        "style": resolve_style(project_dir)["prompt"],
        "style_reference": resolve_style(project_dir)["reference"],
        "characters": role_prompt(roles),
        "negative": negative if negative and "[" not in negative else DEFAULT_NEGATIVE,
        "selected_ids": repair_ids,
        "shots": shots,
    }

    summary = {
        "project": title,
        "shots": len(shots),
        "roles": len(roles),
        "repair_ids": repair_ids,
        "status": "validated" if args.validate_only else "generated",
    }
    if args.validate_only:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0

    skill_dir = Path(__file__).resolve().parent.parent
    template_path = skill_dir / "assets" / "gemini-f12-batch-template.js"
    template = template_path.read_text(encoding="utf-8")
    marker = "/*__PROJECT_CONFIG__*/"
    if template.count(marker) != 1:
        raise ValueError("Gemini 模板配置占位符数量异常。")

    output = (args.output or (project_dir / "Gemini_F12_批量生图.js")).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    generated = template.replace(marker, json.dumps(payload, ensure_ascii=False, indent=2))
    pending = output.with_name(output.stem + ".pending.js")
    pending.write_text(generated, encoding="utf-8", newline="\n")

    node = shutil.which("node")
    if node:
        check = subprocess.run(
            [node, "--check", str(pending)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if check.returncode:
            pending.unlink(missing_ok=True)
            raise RuntimeError("生成的 JavaScript 语法检查失败：\n" + (check.stderr or check.stdout or "未知错误"))
    pending.replace(output)
    summary["output"] = str(output)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
