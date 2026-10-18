"""Final check: real media, existing image/voice results and a brief actual viewing."""
import argparse
from pathlib import Path
from PIL import Image
from final_media import measure
from cover_specs import COVER_SIZES, check_title_outputs
from validate_image_review import validate as validate_images
from validation_cache import now, read_json, sha256, write_json, digest_json
ROOT = Path(__file__).resolve().parent.parent

def local(project, value):
    path = Path(str(value))
    return path if path.is_absolute() else project / path

def binding(project):
    return {'config': digest_json({key: value for key, value in read_json(project / '00_项目配置.json').items() if key != 'covers'}), 'config_file_sha256': sha256(project / '00_项目配置.json'), 'recipe': sha256(project / 'work/recipe.json'),
            'captions': sha256(project / 'work/captions.srt'),
            'covers': {label: sha256(project / '最终成片' / f'封面_{label}.jpg')
                       if (project / '最终成片' / f'封面_{label}.jpg').is_file() else None for label in COVER_SIZES},
            'cover_layout': sha256(project / 'work/cover_layout_validation.json') if (project / 'work/cover_layout_validation.json').is_file() else None}

def prepare_review(project, source):
    path = project / 'work/final_av_review.json'
    current = sha256(source)
    if path.is_file():
        old = read_json(path)
        current_binding = binding(project)
        if old.get('source_sha256') == current and old.get('schema_version') == 2:
            if old.get('binding') == current_binding: return path
            old_binding = old.get('binding', {})
            same_config = (old_binding.get('config') == current_binding.get('config') or
                           ('config_file_sha256' not in old_binding and old_binding.get('config') == current_binding['config_file_sha256']))
            if same_config and all(old_binding.get(key) == current_binding.get(key) for key in ('recipe', 'captions')):
                old.update(binding=current_binding, covers_ok=False)
                write_json(path, old)
                return path
        backup = project / 'work/archive/rollback/final-review.json'
        backup.parent.mkdir(parents=True, exist_ok=True); backup.write_bytes(path.read_bytes())
    data = read_json(ROOT / 'assets/final-av-review-template.json')
    data.update(source=str(source), source_sha256=current, binding=binding(project))
    write_json(path, data)
    return path

def validate(project, source, ffmpeg=None, ffprobe=None):
    config_path = project / '00_项目配置.json'; config = read_json(config_path)
    recipe_path = project / 'work/recipe.json'; recipe = read_json(recipe_path)
    review_path = project / 'work/final_av_review.json'; review = read_json(review_path)
    images = validate_images(project)
    audio = local(project, config.get('voiceover', {}).get('processed_audio', ''))
    voice = read_json(project / 'work/audio_input_check.json')
    input_review = project / 'work/audio_input_review.json'
    mix = read_json(project / 'work/validation.json')
    asr_path = project / 'work/asr_processed.json'; asr = read_json(asr_path)
    media = measure(source, float(recipe['duration_seconds']), ffmpeg, ffprobe)
    intro = config['intro']
    opening = int(intro['cold_hook']['duration_frames']) + int(intro['duration_frames'])
    checks = dict(media['checks'])
    checks.update({
        'opening_fits_video': 0 < opening <= media['actual_frames'],
        'mix_is_current': mix.get('passed') is True and mix.get('output_sha256') == sha256(source)
            and audio.is_file() and sha256(audio) in mix.get('source_hashes', {}).values(),
        'current_images_reviewed': images['passed'],
        'voice_machine_check_passed': voice.get('passed') is True and input_review.is_file()
            and voice.get('review_sha256') == sha256(input_review),
        'voice_matches_current_script': voice.get('script_sha256') == sha256(project / '02_配音稿.txt')
            and voice.get('content_review_current') is True,
        'voice_and_ASR_current': audio.is_file() and voice.get('audio_sha256') == sha256(audio)
            and asr.get('audio_sha256') == sha256(audio) and voice.get('asr_sha256') == sha256(asr_path),
        'final_view_is_current': review.get('schema_version') == 2 and review.get('source_sha256') == sha256(source) and review.get('binding') == binding(project),
        'actual_opening_viewed': review.get('opening_complete') is True,
        'captions_and_body_viewed': review.get('body_ok') is True,
        'covers_viewed': review.get('covers_ok') is True,
        'complete_cover_titles_current': check_title_outputs(project),
        'no_known_major_errors': review.get('major_errors') == [],
        'audio_review_mode_recorded': review.get('audio_mode') in {'listening', 'machine_only'},
        'audio_review_complete': review.get('audio_mode') == 'machine_only' or review.get('sound_ok') is True,
    })
    covers = {}
    for label, size in COVER_SIZES.items():
        path = project / '最终成片' / f'封面_{label}.jpg'
        try:
            with Image.open(path) as image:
                image.load(); valid = image.size == size
        except OSError: valid = False
        checks[f'cover_{label}_exists_and_has_expected_size'] = valid
        covers[label] = sha256(path) if path.is_file() else None
    return {'passed': all(checks.values()), 'created_at': now(), 'checks': checks,
            'source': str(source), 'source_sha256': sha256(source),
            'recipe': str(recipe_path), 'recipe_sha256': sha256(recipe_path),
            'episode_config': str(config_path), 'episode_config_sha256': sha256(config_path),
            'review': str(review_path), 'review_sha256': sha256(review_path),
            'cover_hashes': covers, 'media': media,
            'warnings': ['未做直接听感复核'] if review.get('audio_mode') == 'machine_only' else []}

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('project_dir', type=Path);p.add_argument('--source', type=Path)
    p.add_argument('--ffmpeg', type=Path);p.add_argument('--ffprobe', type=Path)
    p.add_argument('--prepare', action='store_true');a = p.parse_args()
    project = a.project_dir.resolve();source = (a.source or project / 'work/remix.mp4').resolve()
    try:
        if a.prepare: print(prepare_review(project, source));return 0
        report = validate(project, source, a.ffmpeg, a.ffprobe)
    except (OSError, ValueError, KeyError, TypeError) as error:
        report = {'passed': False, 'failures': [str(error)]}
    write_json(project / 'work/delivery_validation.json', report)
    print(__import__('json').dumps(report, ensure_ascii=False))
    return 0 if report['passed'] else 2

if __name__ == '__main__': raise SystemExit(main())
