#!/usr/bin/env python3
"""把 SRT 规范为安全、自然、单行的中文字幕，并输出硬校验报告。"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from caption_utils import clean_caption_text, display_units, split_caption_text
from font_utils import resolve_font
from narration_alignment import normalize, occurrences, words_from_asr
from validation_cache import read_json, sha256, write_json


TIME_RE = re.compile(r"(\d{2}):(\d{2}):(\d{2})[,.](\d{3})\s+-->\s+(\d{2}):(\d{2}):(\d{2})[,.](\d{3})")


def to_seconds(values: tuple[str, str, str, str]) -> float:
    h, m, s, ms = map(int, values)
    return h * 3600 + m * 60 + s + ms / 1000


def timestamp(value: float) -> str:
    millis = max(0, round(value * 1000))
    h, remain = divmod(millis, 3_600_000)
    m, remain = divmod(remain, 60_000)
    s, ms = divmod(remain, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def parse_srt(path: Path) -> list[dict]:
    blocks = re.split(r"\r?\n\s*\r?\n", path.read_text(encoding="utf-8-sig").strip())
    cues = []
    for block in blocks:
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        match = next((TIME_RE.fullmatch(line) for line in lines if TIME_RE.fullmatch(line)), None)
        if not match:
            continue
        time_index = next(index for index, line in enumerate(lines) if TIME_RE.fullmatch(line))
        text = "".join(lines[time_index + 1 :])
        cues.append({"start": to_seconds(match.groups()[:4]), "end": to_seconds(match.groups()[4:]), "text": text})
    return cues


def normalize_cues(cues: list[dict], max_units: float, words=None) -> list[dict]:
    output = []
    for cue in cues:
        parts = split_caption_text(cue["text"], max_units=max_units)
        if not parts:
            continue
        if len(parts) == 1:
            output.append({**cue, 'text': parts[0]})
            continue
        if not words:
            raise ValueError('Caption needs splitting: supply current --asr and --audio; word-count timing is prohibited')
        found = [item for item in occurrences(words, cue['text']) if item['at_word_boundary']
                 and abs(item['start'] - cue['start']) <= 1 / 60 + .002
                 and item['end'] <= cue['end'] + .002]
        if len(found) != 1:
            raise ValueError('Cannot uniquely align full caption to its current audio window')
        match = found[0]
        word_starts, cursor = {}, 0
        for word in words[match['word_index']:match['last_word_index'] + 1]:
            word_starts[cursor] = word['start']
            cursor += len(word['text'])
        if ''.join(map(normalize, parts)) != normalize(cue['text']):
            raise ValueError('Caption split changed spoken content')
        boundaries, cursor = [float(cue['start'])], 0
        for part in parts[:-1]:
            cursor += len(normalize(part))
            if cursor not in word_starts:
                raise ValueError('Subtitle split falls inside an ASR token; re-align or choose another semantic boundary')
            boundaries.append(word_starts[cursor])
        boundaries.append(float(cue['end']))
        if any(b <= a for a, b in zip(boundaries, boundaries[1:])):
            raise ValueError('Non-monotonic caption split times')
        output.extend({'start': boundaries[i], 'end': boundaries[i + 1], 'text': part}
                      for i, part in enumerate(parts))
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--max-caption-units", type=float, default=15.0)
    parser.add_argument("--font-size", type=int, default=60)
    parser.add_argument("--canvas-width", type=int, default=1920)
    parser.add_argument("--horizontal-margin", type=int, default=120)
    parser.add_argument('--asr', type=Path, help='Current audio-bound word timestamps, required when splitting')
    parser.add_argument('--audio', type=Path, help='Current processed narration corresponding to --asr')
    args = parser.parse_args()

    source = args.input.resolve()
    output = (args.output or source).resolve()
    report_path = (args.report or output.parent / "caption_layout_validation.json").resolve()
    try:
        words = None
        if args.asr or args.audio:
            if not args.asr or not args.audio:
                raise ValueError('Pass both --asr and --audio')
            asr = read_json(args.asr)
            if asr.get('audio_sha256') != sha256(args.audio):
                raise ValueError('Subtitle ASR belongs to different audio')
            words = words_from_asr(asr)
        normalized = normalize_cues(parse_srt(source), args.max_caption_units, words)
        if not normalized:
            raise ValueError('No valid subtitle cues; source is unchanged')
    except (OSError, ValueError, TypeError) as exc:
        write_json(report_path, {'passed': False, 'failures': [str(exc)], 'source': str(source)})
        print(str(exc))
        return 2
    font = ImageFont.truetype(str(resolve_font("bold")), args.font_size)
    probe = ImageDraw.Draw(Image.new("L", (1, 1)))
    safe_width = args.canvas_width - 2 * args.horizontal_margin
    failures = []
    rows = []
    previous_end = -1.0
    for index, cue in enumerate(normalized, 1):
        text = clean_caption_text(cue["text"])
        width = float(probe.textlength(text, font=font))
        row_failures = []
        if "\n" in text or "\r" in text:
            row_failures.append("embedded_newline")
        if display_units(text) > args.max_caption_units + 1e-6:
            row_failures.append("display_units_exceeded")
        if width > safe_width:
            row_failures.append("pixel_width_exceeded")
        if cue["start"] < previous_end - 0.001 or cue["end"] <= cue["start"]:
            row_failures.append("invalid_or_overlapping_time")
        previous_end = cue["end"]
        failures.extend(f"#{index}:{item}" for item in row_failures)
        rows.append({"index": index, "text": text, "units": round(display_units(text), 2), "pixel_width": round(width, 2), "failures": row_failures})

    payload = []
    for index, cue in enumerate(normalized, 1):
        payload.append(f"{index}\n{timestamp(cue['start'])} --> {timestamp(cue['end'])}\n{clean_caption_text(cue['text'])}\n")
    pending = output.with_suffix(output.suffix + ".pending")
    pending.write_text("\ufeff" + "\n".join(payload), encoding="utf-8")
    pending.replace(output)
    report = {
        "passed": not failures,
        "input": str(source),
        "output": str(output),
        "cue_count": len(normalized),
        "output_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
        "style": {"font_size_px": args.font_size, "horizontal_margin_px": args.horizontal_margin, "safe_width_px": safe_width, "max_caption_units": args.max_caption_units},
        "failures": failures,
        "cues": rows,
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"passed": report["passed"], "output": str(output), "report": str(report_path), "cue_count": len(normalized)}, ensure_ascii=False))
    return 0 if report["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
