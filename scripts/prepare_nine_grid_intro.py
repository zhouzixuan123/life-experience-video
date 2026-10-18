#!/usr/bin/env python3
"""Install the two-shot cold hook plus fixed native brand intro."""

from __future__ import annotations

import argparse
import json
import math
import re
import shutil
from pathlib import Path
from PIL import ImageFont
from font_utils import resolve_font


PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
COLORS = {"yellow", "red", "white"}
MOTION_SPEC = json.loads((Path(__file__).resolve().parent.parent / "assets/nine-grid-intro/motion-spec.json").read_text(encoding="utf-8"))
PREVIEW_SOURCE_STARTS = MOTION_SPEC["previewSourceStarts"]
PREVIEW_LAYER_COUNT = len(PREVIEW_SOURCE_STARTS)
HOOK_IMAGE_COUNT = 2
HOOK_BEAT_COUNT = 4
HOOK_COLORS = ["yellow", "red", "yellow", "red"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Install the locked two-shot cold hook and four-preview brand intro.")
    parser.add_argument("project", type=Path, help="existing Remotion project directory")
    parser.add_argument("motion_images", type=Path, nargs="+", help="episode intro motion-layer PNGs")
    parser.add_argument(
        "--hook-images",
        type=Path,
        nargs=HOOK_IMAGE_COUNT,
        required=True,
        metavar=("HOOK_1", "HOOK_2"),
        help="two unique wordless PNGs for the cold hook",
    )
    parser.add_argument("--theme", type=Path, required=True, help="wordless topic-still PNG")
    parser.add_argument(
        "--episode-config",
        type=Path,
        required=True,
        help="episode 00_项目配置.json; title and intro timing are read only from here",
    )
    parser.add_argument("--replace", action="store_true", help="replace installed template assets")
    return parser.parse_args()


def require_png(path: Path) -> Path:
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise SystemExit(f"Missing intro image: {resolved}")
    with resolved.open("rb") as handle:
        if handle.read(8) != PNG_SIGNATURE:
            raise SystemExit(f"Intro image must be a real PNG: {resolved}")
    return resolved


def read_json(path: Path) -> dict:
    resolved = path.expanduser().resolve()
    try:
        return json.loads(resolved.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"Cannot read episode config {resolved}: {exc}") from exc


def normalized_title(value: str) -> str:
    return re.sub(r"[\s，。！？、；：,.!?;:\"'“”‘’《》【】（）()—…]+", "", value)


def build_text_config(episode: dict) -> dict:
    title = str(episode.get("title", "")).strip()
    intro = episode.get("intro")
    if not title or not isinstance(intro, dict):
        raise SystemExit("Episode config must contain root title and intro object.")
    if int(intro.get("preview_layer_count", -1)) != PREVIEW_LAYER_COUNT:
        raise SystemExit("Fixed intro.preview_layer_count is 4; change only in an explicit template redesign.")
    if intro.get("preview_source_starts") != PREVIEW_SOURCE_STARTS:
        raise SystemExit("Fixed intro.preview_source_starts must be [0, 27, 54, 81].")
    if intro.get("theme_subject_side") != "left":
        raise SystemExit("intro.theme_subject_side must be 'left' unless the template is explicitly redesigned.")
    if intro.get("theme_text_side") != "right":
        raise SystemExit("intro.theme_text_side must be 'right' unless the template is explicitly redesigned.")

    lines = intro.get("topic_lines")
    if not isinstance(lines, list) or not 1 <= len(lines) <= 3:
        raise SystemExit("intro.topic_lines must contain one to three lines.")
    flattened = ""
    for line in lines:
        if not isinstance(line, list) or not line:
            raise SystemExit("Each intro.topic_lines item must be a non-empty segment list.")
        for segment in line:
            if not isinstance(segment, dict) or not str(segment.get("text", "")).strip():
                raise SystemExit("Each topic segment needs non-empty text.")
            if segment.get("color") not in COLORS:
                raise SystemExit(f"Unsupported topic color: {segment.get('color')}")
            flattened += str(segment["text"])
    if normalized_title(flattened) != normalized_title(title):
        raise SystemExit("intro.topic_lines do not exactly reproduce root title.")
    if not any(segment["color"] == "red" for line in lines for segment in line):
        raise SystemExit("At least one title emphasis segment must be explicitly colored red.")
    if len(normalized_title(title)) <= 8 and len(lines) != 1:
        raise SystemExit("Short titles of eight characters or fewer must stay on one line.")

    fps = int(intro.get("fps", 60))
    if fps != 60:
        raise SystemExit("The default life-experience template must render at native 60 fps.")
    for key, spec_key in {"visual_base_frames": "visualBaseFrames", "source_duration_frames": "sourceDurationFrames",
                          "topic_source_start": "topicSourceStart", "effect_source_frames": "effectFrames"}.items():
        if key in intro and intro[key] != MOTION_SPEC[spec_key]:
            raise SystemExit(f"{key} must match the installed motion specification")
    visual_base = MOTION_SPEC["visualBaseFrames"]
    source_duration = MOTION_SPEC["sourceDurationFrames"]
    topic_start = MOTION_SPEC["topicSourceStart"]
    effect_frames = MOTION_SPEC["effectFrames"]
    earliest_base_reveal = math.ceil((topic_start + effect_frames) * visual_base / source_duration) + 1
    earliest_reveal = math.ceil(earliest_base_reveal * fps / 30)
    reveal = int(intro.get("topic_reveal_frame", earliest_reveal))
    voice_start = int(intro.get("title_voice_start_frame", reveal))
    if reveal < earliest_reveal:
        raise SystemExit(f"Topic text starts before the effect settles; use frame {earliest_reveal} or later.")
    if voice_start != reveal:
        raise SystemExit("title_voice_start_frame must equal topic_reveal_frame.")

    voice_duration = float(intro.get("title_voice_duration_seconds", 0.0))
    minimum_duration = max(
        5 * fps,
        voice_start + math.ceil(voice_duration * fps) + math.ceil(0.15 * fps),
    )
    duration = int(intro.get("duration_frames", minimum_duration))
    if duration < minimum_duration:
        raise SystemExit(f"intro.duration_frames is too short; minimum is {minimum_duration}.")

    return {
        "schemaVersion": 5,
        "fps": fps,
        "durationInFrames": duration,
        "visualBaseFrames": visual_base,
        "guideText": str(intro.get("guide_text", "今天你要体验的人生副本是")),
        "guideStartFrame": int(intro.get("guide_start_frame", 0)),
        "guideEndFrame": int(intro.get("guide_end_frame", round(1.8 * fps))),
        "topicRevealFrame": reveal,
        "themeSubjectSide": "left",
        "topicTextSide": "right",
        "topicLines": lines,
    }


def build_cold_hook_config(episode: dict) -> dict:
    intro = episode.get("intro")
    if not isinstance(intro, dict):
        raise SystemExit("Episode config must contain intro object.")
    hook = intro.get("cold_hook")
    if not isinstance(hook, dict) or hook.get("enabled") is not True:
        raise SystemExit("intro.cold_hook.enabled must be true.")
    if int(hook.get("image_count", -1)) != HOOK_IMAGE_COUNT:
        raise SystemExit("intro.cold_hook.image_count must be 2.")

    duration = int(hook.get("duration_frames", 0))
    fps = int(intro.get("fps", 60))
    if fps != 60:
        raise SystemExit("intro.fps must be 60.")
    transition = int(hook.get("transition_frames", -1))
    expected_transition = round((4 / 30) * fps)
    if transition != expected_transition:
        raise SystemExit(f"intro.cold_hook.transition_frames must be {expected_transition} at {fps} fps.")
    if hook.get("subtitle_position") != "staggered_center":
        raise SystemExit("intro.cold_hook.subtitle_position must be staggered_center.")
    if not 40 <= int(hook.get("subtitle_font_size", 88)) <= 88:
        raise SystemExit("Cold-hook base font size must be 40..88.")
    if int(hook.get("subtitle_stroke_px", -1)) != 8:
        raise SystemExit("intro.cold_hook.subtitle_stroke_px must be 8.")
    expected_positions = {
        "subtitle_upper_left_px": 190,
        "subtitle_upper_top_px": 315,
        "subtitle_lower_right_px": 190,
        "subtitle_lower_bottom_px": 315,
    }
    for key, expected in expected_positions.items():
        if int(hook.get(key, -1)) != expected:
            raise SystemExit(f"intro.cold_hook.{key} must be {expected}.")
    if hook.get("subtitle_shadow") is not False or hook.get("subtitle_background") is not False:
        raise SystemExit("Cold-hook subtitle shadow and background must both be false.")
    post_pause = int(hook.get("post_hook_pause_frames", 0))
    switches = hook.get("image_switch_frames")
    beats = hook.get("caption_beats")
    if duration <= 0 or fps <= 0:
        raise SystemExit("intro.cold_hook.duration_frames must be positive.")
    minimum_pause = math.ceil(0.4 * fps)
    maximum_pause = math.floor(0.6 * fps)
    if not minimum_pause <= post_pause <= maximum_pause:
        raise SystemExit(
            f"intro.cold_hook.post_hook_pause_frames must be about 0.5 seconds "
            f"({minimum_pause}..{maximum_pause} frames at {fps} fps)."
        )
    if not isinstance(switches, list) or len(switches) != HOOK_IMAGE_COUNT:
        raise SystemExit("intro.cold_hook.image_switch_frames must contain two frames.")
    switches = [int(value) for value in switches]
    if switches[0] != 0 or switches != sorted(set(switches)) or switches[-1] >= duration:
        raise SystemExit("Cold-hook image switch frames must start at 0 and increase within duration.")
    if not isinstance(beats, list) or len(beats) != HOOK_BEAT_COUNT:
        raise SystemExit("intro.cold_hook.caption_beats must contain four voice beats.")

    normalized_beats = []
    for index, (beat, expected_color) in enumerate(zip(beats, HOOK_COLORS, strict=True)):
        if not isinstance(beat, dict):
            raise SystemExit(f"Cold-hook beat {index + 1} must be an object.")
        text = str(beat.get("text", "")).strip()
        start = int(beat.get("start_frame", -1))
        end = int(beat.get("end_frame", -1))
        color = str(beat.get("color", ""))
        if not text or text.startswith("["):
            raise SystemExit(f"Cold-hook beat {index + 1} still contains placeholder text.")
        if color != expected_color:
            raise SystemExit("Cold-hook caption colors must be yellow, red, yellow, red.")
        if start < 0 or end <= start or end > duration:
            raise SystemExit(f"Cold-hook beat {index + 1} has invalid frame bounds.")
        if index and start != int(beats[index - 1].get("end_frame", -2)):
            raise SystemExit("Cold-hook caption beats must be continuous and non-overlapping.")
        size = int(hook.get("subtitle_font_size", 88))
        font_path = str(resolve_font("bold"))
        while size > 40 and ImageFont.truetype(font_path, size).getlength(text) + len(text) + 16 > 1100:
            size -= 1
        if ImageFont.truetype(font_path, size).getlength(text) + len(text) + 16 > 1100:
            raise SystemExit("Cold-hook caption exceeds the layout width even at 40px; change layout explicitly, not the confirmed text.")
        normalized_beats.append(
            {"startFrame": start, "endFrame": end, "text": text, "color": color, "fontSize": size}
        )
    if normalized_beats[0]["startFrame"] != 0:
        raise SystemExit("Cold-hook caption beats must start at frame 0.")
    if normalized_beats[-1]["endFrame"] + post_pause != duration:
        raise SystemExit(
            "Cold-hook duration must equal the fourth caption end plus post_hook_pause_frames."
        )
    if switches[1] != normalized_beats[2]["startFrame"]:
        raise SystemExit("Cold-hook image 2 must start with voice beat 3, after the first full sentence.")

    focus = hook.get("image_focus", [[0.5, 0.5]] * HOOK_IMAGE_COUNT)
    if not isinstance(focus, list) or len(focus) != HOOK_IMAGE_COUNT:
        raise SystemExit("intro.cold_hook.image_focus must contain two [x, y] pairs.")
    normalized_focus = []
    for pair in focus:
        if not isinstance(pair, list) or len(pair) != 2:
            raise SystemExit("Each cold-hook image focus must be [x, y].")
        x, y = float(pair[0]), float(pair[1])
        if not 0 <= x <= 1 or not 0 <= y <= 1:
            raise SystemExit("Cold-hook image focus coordinates must be within 0..1.")
        normalized_focus.append([x, y])

    return {
        "fps": fps,
        "durationInFrames": duration,
        "postHookPauseFrames": post_pause,
        "transitionFrames": transition,
        "imageSwitchFrames": switches,
        "imageFocus": normalized_focus,
        "captionBeats": normalized_beats,
        "subtitle": {
            "position": "staggered_center",
            "fontFamily": str(hook.get("subtitle_font_family", "Microsoft YaHei")),
            "fontSize": int(hook.get("subtitle_font_size", 88)),
            "strokePx": int(hook.get("subtitle_stroke_px", 8)),
            "upperLeftPx": int(hook.get("subtitle_upper_left_px", 190)),
            "upperTopPx": int(hook.get("subtitle_upper_top_px", 315)),
            "lowerRightPx": int(hook.get("subtitle_lower_right_px", 190)),
            "lowerBottomPx": int(hook.get("subtitle_lower_bottom_px", 315)),
            "shadow": False,
            "background": False,
        },
    }


def copy_checked(source: Path, destination: Path, replace: bool) -> None:
    if destination.exists() and not replace:
        raise SystemExit(f"Refusing to overwrite {destination}; inspect it, then use --replace.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def build_slot_sources(motion_images: list[Path], theme: Path) -> list[tuple[int, Path]]:
    if len(motion_images) <= PREVIEW_LAYER_COUNT:
        selected = [motion_images[index % len(motion_images)] for index in range(PREVIEW_LAYER_COUNT)]
    else:
        last = len(motion_images) - 1
        selected = [
            motion_images[round(index * last / (PREVIEW_LAYER_COUNT - 1))]
            for index in range(PREVIEW_LAYER_COUNT)
        ]
    return [*((index, source) for index, source in enumerate(selected, 1)), (10, theme)]


def main() -> None:
    args = parse_args()
    project = args.project.expanduser().resolve()
    if not (project / "package.json").is_file() or not (project / "src").is_dir():
        raise SystemExit(f"Not an existing Remotion project: {project}")

    episode = read_json(args.episode_config)
    text_config = build_text_config(episode)
    hook_config = build_cold_hook_config(episode)
    motion_images = [require_png(path) for path in args.motion_images]
    hook_images = [require_png(path) for path in args.hook_images]
    if len({source.read_bytes() for source in hook_images}) != HOOK_IMAGE_COUNT:
        raise SystemExit("Cold-hook images must be two unique PNG files.")
    theme = require_png(args.theme)
    skill_root = Path(__file__).resolve().parent.parent
    template_root = skill_root / "assets" / "nine-grid-intro"
    hook_template_root = skill_root / "assets" / "two-shot-cold-hook"
    template_files = [
        template_root / "NineGridIntro.tsx",
        template_root / "motion-spec.json",
        template_root / "nine-grid-cache-parameters.json",
    ]
    for source in template_files:
        if not source.is_file():
            raise SystemExit(f"Missing Skill template asset: {source}")
    hook_template_files = [
        hook_template_root / "TwoShotColdHook.tsx",
        hook_template_root / "OpeningSequence.tsx",
    ]
    for source in hook_template_files:
        if not source.is_file():
            raise SystemExit(f"Missing Skill cold-hook template asset: {source}")

    targets = [
        *(project / "public" / "assets" / f"cold-hook-slot-{index:02d}.png" for index in [1, 2]),
        *(project / "public" / "assets" / f"intro-slot-{index:02d}.png" for index in [1, 2, 3, 4, 10]),
        *(project / "src" / "opening" / source.name for source in hook_template_files),
        project / "src" / "opening" / "cold-hook-config.json",
        *(project / "src" / "nine-grid-intro" / source.name for source in template_files),
        project / "src" / "nine-grid-intro" / "intro-text-config.json",
    ]
    if not args.replace:
        existing = [target for target in targets if target.exists()]
        if existing:
            raise SystemExit("Targets already exist; inspect and rerun with --replace:\n" + "\n".join(map(str, existing)))

    for index, source in enumerate(hook_images, 1):
        copy_checked(source, project / "public" / "assets" / f"cold-hook-slot-{index:02d}.png", args.replace)
    for index, source in build_slot_sources(motion_images, theme):
        copy_checked(source, project / "public" / "assets" / f"intro-slot-{index:02d}.png", args.replace)
    for source in hook_template_files:
        copy_checked(source, project / "src" / "opening" / source.name, args.replace)
    for source in template_files:
        copy_checked(source, project / "src" / "nine-grid-intro" / source.name, args.replace)
    hook_text_target = project / "src" / "opening" / "cold-hook-config.json"
    hook_text_target.parent.mkdir(parents=True, exist_ok=True)
    hook_text_target.write_text(json.dumps(hook_config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    text_target = project / "src" / "nine-grid-intro" / "intro-text-config.json"
    text_target.parent.mkdir(parents=True, exist_ok=True)
    text_target.write_text(json.dumps(text_config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    opening_duration = hook_config["durationInFrames"] + text_config["durationInFrames"]
    print(f"Installed 2 cold-hook images + 4 motion layers + 1 topic still; opening duration is {opening_duration} frames.")
    print("Mount OpeningSequence directly at frame 0 in the full composition. Do not embed a rendered intro video.")


if __name__ == "__main__":
    main()
