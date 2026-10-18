"""Measure actual media once, without a comparison render."""
import json, math, re, shutil, subprocess
from fractions import Fraction

def measure(source, expected_seconds, ffmpeg=None, ffprobe=None):
    ffmpeg = str(ffmpeg or shutil.which('ffmpeg') or '')
    ffprobe = str(ffprobe or shutil.which('ffprobe') or '')
    if not ffmpeg or not ffprobe: raise FileNotFoundError('ffmpeg and ffprobe are required')
    if not math.isfinite(expected_seconds) or expected_seconds <= 0: raise ValueError('Invalid recipe duration')
    data = json.loads(subprocess.check_output([ffprobe, '-v', 'error', '-show_streams', '-of', 'json', str(source)], encoding='utf-8'))
    video = next((s for s in data['streams'] if s['codec_type'] == 'video'), {})
    audio = next((s for s in data['streams'] if s['codec_type'] == 'audio'), {})
    fps = float(Fraction(video.get('avg_frame_rate', '0/1')))
    run = subprocess.run([ffmpeg, '-hide_banner', '-nostats', '-xerror', '-i', str(source),
        '-map', '0:v:0', '-map', '0:a:0?', '-af', 'volumedetect', '-fps_mode', 'passthrough',
        '-progress', 'pipe:1', '-f', 'null', '-'], capture_output=True, text=True, encoding='utf-8', errors='replace')
    counts = re.findall(r'^frame=(\d+)', run.stdout, re.M)
    frames = int(counts[-1]) if counts else 0
    volumes = re.findall(r'max_volume:\s*([^\s]+) dB', run.stderr)
    checks = {'video_decodes': run.returncode == 0 and frames > 0,
              'resolution_1920x1080': (video.get('width'), video.get('height')) == (1920, 1080),
              'native_fps_60': abs(fps - 60) < .001,
              'actual_duration_matches_recipe': abs(frames - round(expected_seconds * 60)) <= 2,
              'audio_present_and_non_silent': bool(audio) and bool(volumes) and volumes[-1] != '-inf'}
    return {'passed': all(checks.values()), 'checks': checks, 'actual_frames': frames,
            'actual_fps': fps, 'expected_seconds': expected_seconds,
            'diagnostic': run.stderr[-1200:] if run.returncode else ''}
