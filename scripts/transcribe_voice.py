#!/usr/bin/env python3
"""Transcribe a voiceover with word timestamps into a reusable JSON file."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from validation_cache import dependency, read_json, seal, sha256, snapshot, valid_receipt, write_json


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("audio", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--model", default="small")
    parser.add_argument("--model-dir", required=True, type=Path)
    parser.add_argument("--force", action="store_true", help="Ignore reusable ASR evidence and transcribe again")
    args = parser.parse_args()

    args.model_dir.mkdir(parents=True, exist_ok=True)
    audio_digest = sha256(args.audio)
    deps = [dependency(args.audio), dependency(args.model_dir, 'tree')]
    parameters = {"model": args.model, "language": "zh", "beam_size": 5,
                  "best_of": 5, "word_timestamps": True, "vad_filter": True,
                  "vad_parameters": {"min_silence_duration_ms": 100},
                  "condition_on_previous_text": True, "device": "cpu", "compute_type": "int8"}
    current = snapshot(deps, parameters)
    if not args.force and valid_receipt(args.output, current):
        previous = read_json(args.output)
        if previous.get('audio_sha256') == audio_digest and previous.get('segments'):
            print(f"REUSED_ASR={args.output.resolve()}")
            return 0
    from faster_whisper import WhisperModel

    os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
    model = WhisperModel(
        args.model,
        device="cpu",
        compute_type="int8",
        cpu_threads=max(1, min(8, os.cpu_count() or 4)),
        download_root=str(args.model_dir.resolve()),
    )
    segments, info = model.transcribe(
        str(args.audio.resolve()),
        language="zh",
        beam_size=5,
        best_of=5,
        word_timestamps=True,
        vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 100},
        condition_on_previous_text=True,
    )
    result = {
        "audio": str(args.audio.resolve()),
        "audio_sha256": audio_digest,
        "model": args.model,
        "language": info.language,
        "language_probability": info.language_probability,
        "duration": info.duration,
        "segments": [],
    }
    for index, segment in enumerate(segments):
        words = []
        for word in segment.words or []:
            words.append({
                "text": word.word,
                "start": word.start,
                "end": word.end,
                "probability": word.probability,
            })
        result["segments"].append({
            "id": index,
            "start": segment.start,
            "end": segment.end,
            "text": segment.text.strip(),
            "avg_logprob": segment.avg_logprob,
            "no_speech_prob": segment.no_speech_prob,
            "words": words,
        })
        if (index + 1) % 10 == 0:
            print(f"TRANSCRIBED_SEGMENTS={index + 1}", flush=True)
    if sha256(args.audio) != audio_digest:
        raise RuntimeError("Audio changed during transcription; discard result and retry current audio")
    write_json(args.output, result)
    # First use can download the model; bind the resulting model files too.
    seal(args.output, snapshot(deps, parameters))
    print(f"OUTPUT={args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
