"""Build an audio plan with supplied narration and optional licensed music/SFX."""
from __future__ import annotations
import argparse
import json
import math
import re
import subprocess
from pathlib import Path


def media_duration(ffmpeg, source):
    result = subprocess.run([str(ffmpeg), '-hide_banner', '-i', str(source)],
                            capture_output=True, text=True, encoding='utf-8', errors='replace')
    match = re.search(r'Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)', result.stderr)
    if not match or 'Audio:' not in result.stderr:
        raise ValueError(f'No readable audio track: {source}')
    hours, minutes, seconds = match.groups()
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def build_plan(project, duration, ffmpeg, voice, visual='work/silent_visual.mp4',
               source=None, intro_sfx=None, music_volume=0.12, episode_config=None):
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError('Duration must be positive and finite')
    if not math.isfinite(music_volume) or music_volume < 0.01:
        raise ValueError('Music volume must be at least 0.01')
    if not ffmpeg.is_file():
        raise FileNotFoundError(ffmpeg)
    segments = []
    if source:
        source = source.resolve()
        if not source.is_file():
            raise FileNotFoundError(source)
        length = media_duration(ffmpeg, source)
        if length <= 0.05:
            raise ValueError('Music source too short')
        cursor = 0.0
        while cursor < duration - 1e-6:
            chunk = min(length, duration - cursor)
            segments.append({'name': f'background_music_loop_{len(segments)+1:02d}',
                'source': str(source), 'source_start': 0.0, 'timeline_start': round(cursor, 6),
                'duration': round(chunk, 6), 'volume': music_volume,
                'fade_in': 0.2 if cursor == 0 else 0.0, 'fade_out': 0.0})
            cursor += chunk
        segments[-1]['fade_out'] = min(2.5, segments[-1]['duration'])
    effects = []
    if intro_sfx:
        intro_sfx = intro_sfx.resolve()
        if not intro_sfx.is_file():
            raise FileNotFoundError(intro_sfx)
        config = json.loads((episode_config or project / '00_项目配置.json').read_text(encoding='utf-8-sig'))
        intro = config['intro']
        fps = float(intro['fps'])
        hook = intro['cold_hook']
        if not math.isfinite(fps) or fps <= 0 or hook.get('enabled') is not True or hook['duration_frames'] <= 0:
            raise ValueError('An enabled cold hook with valid timing is required for intro SFX')
        start = hook['duration_frames'] / fps
        length = min(media_duration(ffmpeg, intro_sfx), 2.55, duration - start)
        if length <= 0:
            raise ValueError('Intro SFX starts outside the video')
        effects.append({'name': 'user_intro_sfx', 'source': str(intro_sfx),
            'semantic_anchor': 'brand_intro_fast_switches', 'source_start': 0.0,
            'timeline_start': start, 'duration': length, 'volume': 1.0})
    return {'duration': duration, 'visual': visual, 'voice': {'source': str(voice), 'volume': 1.0},
            'music': {'enabled': bool(source), 'allow_overlap': False, 'allow_source_reuse': True,
                      'allow_gaps': False, 'segments': segments},
            'sound_effects': effects, 'output_audio': {'peak_limit': 0.9},
            'qa': {'final_peak_ceiling_db': -0.3}, 'output': 'work/remix.mp4'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('project_dir', type=Path)
    parser.add_argument('--source', type=Path, help='Explicitly supplied music; omitted means no music')
    parser.add_argument('--intro-sfx', type=Path, help='Explicitly supplied intro sound effect')
    parser.add_argument('--duration', type=float, required=True)
    parser.add_argument('--ffmpeg', type=Path, required=True)
    parser.add_argument('--voice', required=True)
    parser.add_argument('--visual', default='work/silent_visual.mp4')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--music-volume', type=float, default=0.12)
    parser.add_argument('--episode-config', type=Path)
    args = parser.parse_args()
    project = args.project_dir.resolve()
    plan = build_plan(project, args.duration, args.ffmpeg.resolve(), args.voice, args.visual,
                      args.source, args.intro_sfx, args.music_volume, args.episode_config)
    output = (args.output or project / 'work/audio_mix_plan.json').resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'output': str(output), 'music_enabled': plan['music']['enabled'],
                      'sound_effect_count': len(plan['sound_effects'])}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
