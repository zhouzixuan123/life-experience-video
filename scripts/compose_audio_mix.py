#!/usr/bin/env python3
"""Build a life-experience video's audio once from explicit, validated stems.

The visual input is always treated as silent. Narration, music segments and
intro sound effects are rebuilt from their sources so later BGM edits cannot
stack old music or drop an approved sound-effect track.
"""

from __future__ import annotations

import argparse
import atexit
import array
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import wave
from pathlib import Path
from typing import Any


def run(command: list[str]) -> None:
    subprocess.run(command, check=True)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def cleanup_stems(stem_dir: Path, stems: tuple[Path, ...]) -> None:
    for stem in stems:
        try:
            stem.unlink(missing_ok=True)
        except OSError:
            pass
    try:
        stem_dir.rmdir()
    except OSError:
        pass


def probe_media(ffmpeg: Path, media: Path) -> dict[str, Any]:
    result = subprocess.run(
        [str(ffmpeg), "-hide_banner", "-i", str(media)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    duration_match = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", result.stderr)
    if not duration_match:
        raise RuntimeError(f"无法读取媒体时长: {media}")
    hours, minutes, seconds = duration_match.groups()
    duration = int(hours) * 3600 + int(minutes) * 60 + float(seconds)
    audio_line = next((line for line in result.stderr.splitlines() if "Audio:" in line), None)
    channels = None
    if audio_line:
        if re.search(r"\bmono\b", audio_line):
            channels = 1
        elif re.search(r"\bstereo\b", audio_line):
            channels = 2
        else:
            channel_match = re.search(r"\b(\d+) channels\b", audio_line)
            if channel_match:
                channels = int(channel_match.group(1))
    return {"duration": duration, "audio_channels": channels, "audio_line": audio_line}


def volume_stats(ffmpeg: Path, media: Path, start: float = 0.0, duration: float | None = None) -> dict[str, float]:
    command = [str(ffmpeg), "-hide_banner"]
    if start > 0:
        command.extend(["-ss", f"{start:.6f}"])
    if duration is not None:
        command.extend(["-t", f"{duration:.6f}"])
    command.extend(["-i", str(media), "-vn", "-af", "volumedetect", "-f", "null", os.devnull])
    result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace")
    mean_match = re.search(r"mean_volume:\s*(-?[\d.]+|-inf) dB", result.stderr)
    max_match = re.search(r"max_volume:\s*(-?[\d.]+|-inf) dB", result.stderr)
    if not mean_match or not max_match:
        raise RuntimeError(f"无法测量音量: {media} @ {start:.3f}s")
    def db_value(value: str) -> float:
        return -120.0 if value == "-inf" else float(value)

    return {"mean_db": db_value(mean_match.group(1)), "max_db": db_value(max_match.group(1))}


def resolve_path(value: str, project: Path, plan_dir: Path) -> Path:
    if value.startswith("skill://"):
        skill_root = Path(__file__).resolve().parent.parent
        relative = Path(value[len("skill://"):])
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError(f"非法 Skill 资源 URI: {value}")
        resolved = (skill_root / relative).resolve()
        try:
            resolved.relative_to(skill_root)
        except ValueError as exc:
            raise ValueError(f"Skill 资源越出根目录: {value}") from exc
        return resolved
    candidate = Path(value)
    if candidate.is_absolute():
        return candidate.resolve()
    from_plan = (plan_dir / candidate).resolve()
    if from_plan.exists():
        return from_plan
    return (project / candidate).resolve()


def ranges_overlap(first: tuple[float, float], second: tuple[float, float], tolerance: float = 1e-6) -> bool:
    return second[0] < first[1] - tolerance and first[0] < second[1] - tolerance


def validate_segments(
    segments: list[dict[str, Any]],
    total: float,
    allow_overlap: bool,
    allow_source_reuse: bool,
    allow_gaps: bool,
) -> tuple[bool, bool, bool]:
    timeline_ranges = sorted(
        (float(item["timeline_start"]), float(item["timeline_start"]) + float(item["duration"]), item["name"])
        for item in segments
    )
    overlap_detected = any(
        ranges_overlap((a[0], a[1]), (b[0], b[1])) for a, b in zip(timeline_ranges, timeline_ranges[1:])
    )
    if overlap_detected and not allow_overlap:
        raise RuntimeError(f"音乐时间段发生重叠，但计划禁止重叠: {timeline_ranges}")
    if any(start < -1e-6 or end > total + 0.05 or end <= start for start, end, _ in timeline_ranges):
        raise RuntimeError(f"音乐时间段超出成片范围: {timeline_ranges}")

    gap_detected = not timeline_ranges
    covered_end = 0.0
    for start, end, _ in timeline_ranges:
        if start > covered_end + 0.05:
            gap_detected = True
        covered_end = max(covered_end, end)
    gap_detected = gap_detected or covered_end < total - 0.05
    if gap_detected and not allow_gaps:
        raise RuntimeError(f"背景音乐时间轴存在空白，但计划禁止空白: {timeline_ranges}")

    by_source: dict[str, list[tuple[float, float, str]]] = {}
    for item in segments:
        by_source.setdefault(item["resolved_source"], []).append(
            (
                float(item.get("source_start", 0.0)),
                float(item.get("source_start", 0.0)) + float(item["duration"]),
                item["name"],
            )
        )
    source_reuse_detected = False
    for ranges in by_source.values():
        ranges.sort()
        if any(ranges_overlap((a[0], a[1]), (b[0], b[1])) for a, b in zip(ranges, ranges[1:])):
            source_reuse_detected = True
    if source_reuse_detected and not allow_source_reuse:
        raise RuntimeError("同一音乐源的时间段被重复使用，但计划禁止重复使用")
    return overlap_detected, source_reuse_detected, gap_detected


def stereo_filter(channels: int | None) -> str:
    if channels == 1:
        return "pan=stereo|c0=c0|c1=c0"
    return "aformat=channel_layouts=stereo"


def build_stem(
    ffmpeg: Path,
    segments: list[dict[str, Any]],
    output: Path,
    total: float,
) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    if not segments:
        run([
            str(ffmpeg), "-y", "-loglevel", "error", "-f", "lavfi", "-i",
            "anullsrc=r=48000:cl=stereo", "-t", f"{total:.6f}",
            "-c:a", "pcm_s16le", str(output),
        ])
        return

    inputs: list[str] = []
    filters: list[str] = []
    labels: list[str] = []
    for index, item in enumerate(segments):
        inputs.extend(["-i", item["resolved_source"]])
        duration = float(item["duration"])
        source_start = float(item.get("source_start", 0.0))
        timeline_start = float(item["timeline_start"])
        volume = float(item.get("volume", 1.0))
        fade_in = max(0.0, min(duration, float(item.get("fade_in", 0.0))))
        fade_out = max(0.0, min(duration, float(item.get("fade_out", 0.0))))
        chain = [
            f"[{index}:a]atrim=start={source_start:.6f}:duration={duration:.6f}",
            "asetpts=PTS-STARTPTS",
            "aresample=48000",
            stereo_filter(item.get("source_channels")),
            f"volume={volume:.8f}",
        ]
        if fade_in > 0:
            chain.append(f"afade=t=in:st=0:d={fade_in:.6f}")
        if fade_out > 0:
            chain.append(f"afade=t=out:st={duration - fade_out:.6f}:d={fade_out:.6f}")
        delay_ms = round(timeline_start * 1000)
        chain.append(f"adelay={delay_ms}|{delay_ms}")
        label = f"s{index}"
        filters.append(",".join(chain) + f"[{label}]")
        labels.append(f"[{label}]")

    if len(labels) == 1:
        filters.append(f"{labels[0]}apad=pad_dur={total:.6f},atrim=0:{total:.6f},asetpts=PTS-STARTPTS[stem]")
    else:
        filters.append(
            "".join(labels)
            + f"amix=inputs={len(labels)}:duration=longest:dropout_transition=0:normalize=0,"
            + f"apad=pad_dur={total:.6f},atrim=0:{total:.6f},asetpts=PTS-STARTPTS[stem]"
        )
    run([
        str(ffmpeg), "-y", "-loglevel", "error", *inputs,
        "-filter_complex", ";".join(filters), "-map", "[stem]",
        "-ac", "2", "-ar", "48000", "-c:a", "pcm_s16le", str(output),
    ])


def boundary_jump_dbfs(wav_path: Path, timestamp: float) -> float:
    """Measure the largest per-channel sample jump at one PCM seam."""
    with wave.open(str(wav_path), "rb") as stream:
        sample_rate = stream.getframerate()
        channels = stream.getnchannels()
        if stream.getsampwidth() != 2:
            raise RuntimeError(f"边界检测仅支持 PCM16 stem: {wav_path}")
        frame = max(1, min(stream.getnframes() - 1, round(timestamp * sample_rate)))
        stream.setpos(frame - 1)
        values = array.array("h")
        values.frombytes(stream.readframes(2))
    if len(values) < channels * 2:
        return -120.0
    jump = max(abs(values[channels + index] - values[index]) for index in range(channels)) / 32768.0
    return 20.0 * math.log10(max(jump, 1e-6))


def automatic_music_sample_times(
    requested: list[float],
    segments: list[dict[str, Any]],
    total: float,
    max_interval: float,
    boundary_offset: float,
) -> list[float]:
    times = {max(0.0, min(total, float(value))) for value in requested}
    if total > 0:
        times.update({min(2.0, total / 2), max(0.0, total - 2.0)})
    cursor = min(2.0, total / 2)
    while cursor < total:
        times.add(cursor)
        cursor += max(5.0, max_interval)
    boundaries = sorted({
        float(item["timeline_start"])
        for item in segments
        if 0.05 < float(item["timeline_start"]) < total - 0.05
    })
    for boundary in boundaries:
        times.add(max(0.0, boundary - boundary_offset))
        times.add(min(total, boundary + boundary_offset))
    return sorted(times)


def prepare_segments(
    raw_segments: list[dict[str, Any]],
    project: Path,
    plan_dir: Path,
    ffmpeg: Path,
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    prepared: list[dict[str, Any]] = []
    hashes: dict[str, str] = {}
    probes: dict[str, dict[str, Any]] = {}
    for index, raw in enumerate(raw_segments):
        item = dict(raw)
        item.setdefault("name", f"segment_{index + 1}")
        source = resolve_path(str(item["source"]), project, plan_dir)
        if not source.is_file():
            raise FileNotFoundError(source)
        key = str(source)
        probe = probes.setdefault(key, probe_media(ffmpeg, source))
        if probe["audio_channels"] is None:
            raise RuntimeError(f"指定素材没有音轨: {source}")
        source_start = float(item.get("source_start", 0.0))
        duration = float(item["duration"])
        if source_start < 0 or duration <= 0 or source_start + duration > probe["duration"] + 0.05:
            raise RuntimeError(
                f"音频取段超出源文件: {source}, {source_start:.3f}+{duration:.3f}>{probe['duration']:.3f}"
            )
        item["resolved_source"] = key
        item["source_channels"] = probe["audio_channels"]
        prepared.append(item)
        hashes[key] = hashes.get(key) or sha256(source)
    return prepared, hashes


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("project_dir", type=Path)
    parser.add_argument("plan", type=Path)
    parser.add_argument("--ffmpeg", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--validation-output", type=Path)
    parser.add_argument("--no-project-metadata", action="store_true")
    parser.add_argument(
        "--keep-stems",
        action="store_true",
        help="保留可重建的未压缩混音中间轨；默认在校验完成后删除。",
    )
    parser.add_argument("--diagnostics", action="store_true", help="Optional detailed sound-level diagnostics; findings are warnings")
    args = parser.parse_args()

    project = args.project_dir.resolve()
    work = project / "work"
    plan_path = args.plan.resolve()
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    ffmpeg = args.ffmpeg.resolve()
    total = float(plan["duration"])
    plan_dir = plan_path.parent

    visual = resolve_path(str(plan["visual"]), project, plan_dir)
    voice_path = resolve_path(str(plan["voice"]["source"]), project, plan_dir)
    if not visual.is_file() or not voice_path.is_file():
        raise FileNotFoundError(f"缺少画面或配音: {visual}, {voice_path}")
    voice_probe = probe_media(ffmpeg, voice_path)
    if voice_probe["audio_channels"] is None or voice_probe["duration"] + 0.05 < total:
        raise RuntimeError("配音无音轨或短于成片")

    music_config = plan.get("music", {})
    music, music_hashes = prepare_segments(music_config.get("segments", []), project, plan_dir, ffmpeg)
    music_enabled = music_config.get("enabled", True)
    if not music and music_enabled:
        raise RuntimeError("音频计划至少需要一段背景音乐；用户明确无音乐时设 music.enabled=false")
    if not music_enabled and music:
        raise ValueError("Disabled music must have no segments")
    if music_enabled:
        music_overlap, source_reuse, music_gaps = validate_segments(
            music, total, bool(music_config.get("allow_overlap", False)),
            bool(music_config.get("allow_source_reuse", True)), bool(music_config.get("allow_gaps", False)))
    else:
        music_overlap, source_reuse, music_gaps = [], [], []
    sfx, sfx_hashes = prepare_segments(plan.get("sound_effects", []), project, plan_dir, ffmpeg)
    semantic_sfx_timing_checks = []
    anchored_sfx = [
        item for item in sfx
        if item.get("semantic_anchor") == "brand_intro_fast_switches"
    ]
    if anchored_sfx:
        config_path = project / "00_项目配置.json"
        if not config_path.is_file():
            raise FileNotFoundError(f"缺少项目配置，无法校验品牌片头音效锚点: {config_path}")
        config = json.loads(config_path.read_text(encoding="utf-8-sig"))
        intro = config.get("intro", {})
        cold_hook = intro.get("cold_hook", {})
        fps = float(intro.get("fps", 60))
        hook_frames = int(cold_hook.get("duration_frames", 0)) if cold_hook.get("enabled") is True else 0
        if fps <= 0 or hook_frames <= 0:
            raise ValueError("intro.fps 和启用后的 cold_hook.duration_frames 必须为正数")
        expected_start = hook_frames / fps
        tolerance = 1 / fps + 0.002
        for item in anchored_sfx:
            actual_start = float(item["timeline_start"])
            semantic_sfx_timing_checks.append({
                "name": item["name"],
                "semantic_anchor": item["semantic_anchor"],
                "expected_timeline_start": expected_start,
                "actual_timeline_start": actual_start,
                "tolerance_seconds": tolerance,
                "passed": abs(actual_start - expected_start) <= tolerance,
            })
        failed_timing = [item for item in semantic_sfx_timing_checks if not item["passed"]]
        if failed_timing:
            raise RuntimeError(
                "品牌片头齿轮声位置错误：必须从两图冷开场结束后的快速拼贴首帧进入。"
                f"详情: {failed_timing}"
            )

    stem_dir = work / "audio_stems"
    music_stem = stem_dir / "background_music.wav"
    sfx_stem = stem_dir / "sound_effects.wav"
    generated_stems = (music_stem, sfx_stem)
    if not args.keep_stems:
        atexit.register(cleanup_stems, stem_dir, generated_stems)
    build_stem(ffmpeg, music, music_stem, total)
    build_stem(ffmpeg, sfx, sfx_stem, total)

    output = (args.output.resolve() if args.output else resolve_path(str(plan.get("output", "work/remix.mp4")), project, plan_dir))
    output.parent.mkdir(parents=True, exist_ok=True)
    archive = None
    if output.exists() and output.resolve() == (work / "remix.mp4").resolve():
        archive_root = work / "archive"
        archive = archive_root / "audio_compose_previous"
        archive_root.mkdir(parents=True, exist_ok=True)
        if archive.exists():
            if archive.resolve().parent != archive_root.resolve():
                raise RuntimeError("音频回退目录越出 work/archive")
            shutil.rmtree(archive)
        archive.mkdir(parents=True, exist_ok=False)
        try:
            os.link(output, archive / output.name)
        except OSError:
            shutil.copy2(output, archive / output.name)
        for metadata in (work / "recipe.json", work / "validation.json", work / "delivery_validation.json"):
            if metadata.is_file():
                shutil.copy2(metadata, archive / metadata.name)

    pending = output.with_name(output.stem + ".pending" + output.suffix)
    voice_volume = float(plan["voice"].get("volume", 1.0))
    peak_limit = float(plan.get("output_audio", {}).get("peak_limit", 0.90))
    mix_filter = (
        f"[1:a]atrim=0:{total:.6f},asetpts=PTS-STARTPTS,aresample=48000,"
        f"{stereo_filter(voice_probe['audio_channels'])},volume={voice_volume:.8f}[voice];"
        f"[2:a]atrim=0:{total:.6f},asetpts=PTS-STARTPTS[bgm];"
        f"[3:a]atrim=0:{total:.6f},asetpts=PTS-STARTPTS[sfx];"
        "[voice][bgm][sfx]amix=inputs=3:duration=longest:dropout_transition=0:normalize=0,"
        f"alimiter=limit={peak_limit:.6f}:level=disabled[mix]"
    )
    run([
        str(ffmpeg), "-y", "-loglevel", "error",
        "-i", str(visual), "-i", str(voice_path), "-i", str(music_stem), "-i", str(sfx_stem),
        "-filter_complex", mix_filter, "-map", "0:v:0", "-map", "[mix]",
        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
        "-t", f"{total:.6f}", "-movflags", "+faststart", str(pending),
    ])
    pending.replace(output)

    output_probe = probe_media(ffmpeg, output)
    final_stats = volume_stats(ffmpeg, output)
    qa = plan.get("qa", {})
    sample_window = float(qa.get("sample_window", 4.0))
    max_sample_interval = min(60.0, float(qa.get("max_sample_interval", 60.0)))
    boundary_offset = float(qa.get("boundary_probe_offset", 1.0))
    sample_times = automatic_music_sample_times(
        qa.get("music_sample_times", []), music, total, max_sample_interval, boundary_offset
    ) if args.diagnostics else []
    music_samples = []
    for timestamp in sample_times:
        start = max(0.0, min(total - sample_window, float(timestamp) - sample_window / 2))
        stats = volume_stats(ffmpeg, music_stem, start, sample_window)
        voice_stats = volume_stats(ffmpeg, voice_path, start, sample_window)
        music_samples.append({
            "time": float(timestamp),
            **stats,
            "voice_mean_db": voice_stats["mean_db"],
            "voice_active": voice_stats["mean_db"] > -60.0,
            "music_minus_voice_db": stats["mean_db"] - voice_stats["mean_db"],
        })
    internal_boundaries = sorted({
        float(item["timeline_start"])
        for item in music
        if 0.05 < float(item["timeline_start"]) < total - 0.05
    })
    max_boundary_jump = min(-30.0, float(qa.get("max_boundary_jump_dbfs", -30.0)))
    boundary_checks = [
        {
            "time": timestamp,
            "jump_dbfs": boundary_jump_dbfs(music_stem, timestamp),
        }
        for timestamp in (internal_boundaries if args.diagnostics else [])
    ]
    for item in boundary_checks:
        item["passed"] = item["jump_dbfs"] <= max_boundary_jump
    sfx_checks = []
    for check in (qa.get("sound_effect_checks", []) if args.diagnostics else []):
        stats = volume_stats(ffmpeg, sfx_stem, float(check["start"]), float(check["duration"]))
        matching = next((item for item in sfx if item["name"] == check["name"]), None)
        expected_start = check.get("expected_timeline_start")
        tolerance = float(check.get("start_tolerance_seconds", 0.035333))
        timing_passed = matching is not None and (
            expected_start is None
            or abs(float(matching["timeline_start"]) - float(expected_start)) <= tolerance
        )
        loudness_passed = stats["mean_db"] >= float(check.get("min_mean_db", -50.0)) and stats["max_db"] >= float(
            check.get("min_peak_db", -24.0)
        )
        sfx_checks.append({
            "name": check["name"],
            "passed": loudness_passed and timing_passed,
            "loudness_passed": loudness_passed,
            "timing_passed": timing_passed,
            "expected_timeline_start": expected_start,
            "actual_timeline_start": None if matching is None else float(matching["timeline_start"]),
            **stats,
        })

    nonstandard_level_authorized = bool(qa.get("allow_nonstandard_music_level", False))
    if nonstandard_level_authorized:
        music_min_mean = float(qa.get("music_min_mean_db", -38.0))
        music_relative_min = float(qa.get("music_relative_min_db", -18.0))
        music_relative_max = float(qa.get("music_relative_max_db", -8.0))
    else:
        # Plans cannot silently weaken the standard audibility gate.
        music_min_mean = max(-38.0, float(qa.get("music_min_mean_db", -38.0)))
        music_relative_min = max(-18.0, float(qa.get("music_relative_min_db", -18.0)))
        music_relative_max = min(-8.0, float(qa.get("music_relative_max_db", -8.0)))
    final_peak_ceiling = float(qa.get("final_peak_ceiling_db", -0.3))
    timeline_ranges = sorted(
        (float(item["timeline_start"]), float(item["timeline_start"]) + float(item["duration"]))
        for item in music
    )
    coverage_points = [0.0, *sample_times, total]
    largest_sample_gap = max((b - a for a, b in zip(coverage_points, coverage_points[1:])), default=total)
    checks = {
        "duration_matches": abs(output_probe["duration"] - total) < 0.05,
        "stereo_output": output_probe["audio_channels"] == 2,
        "music_policy_satisfied": not music_overlap or bool(music_config.get("allow_overlap", False)),
        "source_reuse_policy_satisfied": not source_reuse or bool(music_config.get("allow_source_reuse", True)),
        "music_gap_policy_satisfied": not music_gaps or bool(music_config.get("allow_gaps", False)),
        "music_starts_at_zero": not music_enabled or bool(timeline_ranges) and timeline_ranges[0][0] <= 0.01,
        "music_ends_with_video": not music_enabled or bool(timeline_ranges) and timeline_ranges[-1][1] >= total - 0.05,
        "music_segment_volumes_positive": all(float(item.get("volume", 1.0)) >= 0.01 for item in music),
        "music_samples_cover_timeline": len(music_samples) >= 3,
        "music_sample_density_satisfied": largest_sample_gap <= max_sample_interval + 0.05,
        "music_audible_at_samples": bool(music_samples) and all(
            item["mean_db"] >= music_min_mean and
            (
                not item["voice_active"] or
                music_relative_min <= item["music_minus_voice_db"] <= music_relative_max
            )
            for item in music_samples
        ),
        "music_boundary_seams_pass": all(item["passed"] for item in boundary_checks),
        "sound_effects_pass": all(item["passed"] for item in sfx_checks),
        "sound_effects_checked": not sfx or bool(sfx_checks),
        "sound_effect_timing_pass": all(item["passed"] for item in semantic_sfx_timing_checks),
        "final_peak_safe": final_stats["max_db"] <= final_peak_ceiling,
    }
    advisory_keys = {"music_samples_cover_timeline", "music_sample_density_satisfied", "music_audible_at_samples",
                     "music_boundary_seams_pass", "sound_effects_pass", "sound_effects_checked"}
    diagnostic_checks = {key: checks.pop(key) for key in advisory_keys}
    warnings = [key for key, passed in diagnostic_checks.items() if not passed] if args.diagnostics else []
    source_hashes = {
        str(visual): sha256(visual),
        str(voice_path): sha256(voice_path),
        **music_hashes,
        **sfx_hashes,
    }
    validation = {
        "passed": all(checks.values()),
        "checks": checks,
        "warnings": warnings,
        "diagnostics": diagnostic_checks if args.diagnostics else None,
        "plan": str(plan_path),
        "plan_sha256": sha256(plan_path),
        "output": str(output),
        "output_sha256": sha256(output),
        "output_duration": output_probe["duration"],
        "output_audio_channels": output_probe["audio_channels"],
        "final_audio": final_stats,
        "music_overlap_allowed": bool(music_config.get("allow_overlap", False)),
        "music_overlap_detected": music_overlap,
        "source_reuse_allowed": bool(music_config.get("allow_source_reuse", True)),
        "source_reuse_detected": source_reuse,
        "music_gaps_allowed": bool(music_config.get("allow_gaps", False)),
        "music_gaps_detected": music_gaps,
        "source_hashes": source_hashes,
        "music_stem": str(music_stem) if args.keep_stems else None,
        "sound_effects_stem": str(sfx_stem) if args.keep_stems else None,
        "temporary_stems_removed": not args.keep_stems,
        "music_samples": music_samples,
        "music_boundary_checks": boundary_checks,
        "music_qa_thresholds": {
            "sample_window": sample_window,
            "max_sample_interval": max_sample_interval,
            "music_min_mean_db": music_min_mean,
            "music_relative_min_db": music_relative_min,
            "music_relative_max_db": music_relative_max,
            "max_boundary_jump_dbfs": max_boundary_jump,
            "nonstandard_level_authorized": nonstandard_level_authorized,
        },
        "sound_effect_checks": sfx_checks,
        "semantic_sound_effect_timing_checks": semantic_sfx_timing_checks,
        "archive": str(archive) if archive else None,
    }
    validation_output = (
        args.validation_output.resolve() if args.validation_output else work / "validation.json"
    )
    validation_output.parent.mkdir(parents=True, exist_ok=True)
    validation_output.write_text(json.dumps(validation, ensure_ascii=False, indent=2), encoding="utf-8")

    if not args.no_project_metadata:
        recipe_path = work / "recipe.json"
        recipe = json.loads(recipe_path.read_text(encoding="utf-8")) if recipe_path.is_file() else {}
        recipe["duration"] = total
        recipe["voice"] = str(voice_path)
        if music:
            recipe["bgm"] = str(music[0]["resolved_source"])
        else:
            recipe.pop("bgm", None)
        recipe["audio_mix"] = {
            "plan": str(plan_path),
            "plan_sha256": validation["plan_sha256"],
            "music": music_config,
            "sound_effects": plan.get("sound_effects", []),
            "source_hashes": source_hashes,
            "music_stem": str(music_stem) if args.keep_stems else None,
            "sound_effects_stem": str(sfx_stem) if args.keep_stems else None,
            "temporary_stems_removed": not args.keep_stems,
            "stereo_output": True,
        }
        recipe_path.write_text(json.dumps(recipe, ensure_ascii=False, indent=2), encoding="utf-8")

    if not args.keep_stems:
        cleanup_stems(stem_dir, generated_stems)
        atexit.unregister(cleanup_stems)

    print(json.dumps(validation, ensure_ascii=False))
    return 0 if validation["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
