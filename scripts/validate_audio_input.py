"""Validate supplied audio and its transcript; does not generate or edit audio."""
from __future__ import annotations
import argparse
import json
import math
import shutil
import subprocess
from pathlib import Path
from validation_cache import now, read_json, sha256, write_json


def local(project, value):
    path = Path(value)
    return path.resolve() if path.is_absolute() else (project / path).resolve()


def inputs(project, audio=None, asr=None):
    config = read_json(project / '00_项目配置.json')
    return {'audio': local(project, audio or config['voiceover']['processed_audio']),
            'asr': local(project, asr or 'work/asr_processed.json'),
            'script': project / '02_配音稿.txt'}


def binding(paths):
    return {key + '_sha256': sha256(path) for key, path in paths.items()}


def prepare(paths, review):
    current = binding(paths)
    if review.is_file():
        old = read_json(review)
        if all(old.get(key) == value for key, value in current.items()):
            return
    write_json(review, {**current, 'content_matches_script': None, 'notes': ''})


def validate(paths, review, ffmpeg=None, ffprobe=None):
    ffmpeg = str(ffmpeg or shutil.which('ffmpeg') or '')
    ffprobe = str(ffprobe or shutil.which('ffprobe') or '')
    if not ffmpeg or not ffprobe:
        raise FileNotFoundError('FFmpeg and ffprobe must be installed')
    current = binding(paths)
    metadata = subprocess.run([ffprobe, '-v', 'error', '-show_format', '-show_streams',
                               '-of', 'json', str(paths['audio'])],
                              check=True, capture_output=True, text=True, encoding='utf-8')
    media = json.loads(metadata.stdout)
    duration = float(media.get('format', {}).get('duration', 0))
    decoded = subprocess.run([ffmpeg, '-v', 'error', '-i', str(paths['audio']),
                              '-map', '0:a:0', '-f', 'null', '-'], capture_output=True)
    asr = read_json(paths['asr'])
    words = [word for segment in asr.get('segments', []) for word in segment.get('words', [])]
    previous_start = -1.0
    valid_times = bool(words)
    for word in words:
        start, end = float(word['start']), float(word['end'])
        valid_times &= (math.isfinite(start) and math.isfinite(end)
                        and 0 <= start < end <= duration + 0.1 and start >= previous_start)
        previous_start = start
    observation = read_json(review) if review.is_file() else {}
    review_current = all(observation.get(key) == value for key, value in current.items())
    content_current = review_current and observation.get('content_matches_script') is True
    checks = {'audio_stream_present': any(s.get('codec_type') == 'audio' for s in media.get('streams', [])),
              'duration_positive': math.isfinite(duration) and duration > 0,
              'audio_decodes': decoded.returncode == 0,
              'transcript_matches_audio': asr.get('audio_sha256') == current['audio_sha256'],
              'word_times_valid': bool(valid_times), 'content_review_current': content_current}
    return {'passed': all(checks.values()), 'created_at': now(), 'checks': checks,
            **current, 'content_review_current': content_current,
            'review': str(review), 'review_sha256': sha256(review) if review.is_file() else None,
            'duration_seconds': duration,
            'limitation': 'Checks supplied files and current review; does not assess pronunciation or generate speech.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('project', type=Path)
    parser.add_argument('--audio', type=Path)
    parser.add_argument('--asr', type=Path)
    parser.add_argument('--review', type=Path)
    parser.add_argument('--ffmpeg', type=Path)
    parser.add_argument('--ffprobe', type=Path)
    parser.add_argument('--prepare', action='store_true')
    parser.add_argument('--machine-only', action='store_true', help='Compatibility flag; no listening is claimed')
    args = parser.parse_args()
    project = args.project.resolve()
    review = (args.review or project / 'work/audio_input_review.json').resolve()
    try:
        paths = inputs(project, args.audio, args.asr)
        if args.prepare:
            prepare(paths, review)
            print(json.dumps({'review': str(review), 'requires_content_review': True}, ensure_ascii=False))
            return 0
        report = validate(paths, review, args.ffmpeg, args.ffprobe)
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        report = {'passed': False, 'failures': [str(error)]}
    write_json(project / 'work/audio_input_check.json', report)
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report['passed'] else 2


if __name__ == '__main__':
    raise SystemExit(main())
