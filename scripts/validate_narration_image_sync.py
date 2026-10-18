#!/usr/bin/env python3
"""Recompute shot/word alignment from current audio-bound ASR and render recipe."""
from __future__ import annotations

import argparse
from pathlib import Path

from narration_alignment import finite, occurrences, words_from_asr
from validation_cache import now, read_json, sha256, write_json


def project_path(project, value):
    path = Path(str(value))
    return path.resolve() if path.is_absolute() else (project / path).resolve()


def inputs(project: Path, matches=None, asr=None, audio=None, recipe=None) -> dict:
    recipe_path = recipe or project / 'work/recipe.json'
    data = read_json(recipe_path)
    config = read_json(project / '00_项目配置.json') if (project / '00_项目配置.json').is_file() else {}
    source = audio or config.get('voiceover', {}).get('processed_audio') or data.get('voice') or data.get('voice_path')
    if not source:
        raise ValueError('Set voiceover.processed_audio or recipe.voice to the final full-timeline voice WAV')
    return {'matches': (matches or project / 'work/matches.json').resolve(),
            'asr': (asr or project / 'work/asr_processed.json').resolve(),
            'audio': project_path(project, source), 'recipe': recipe_path.resolve(),
            'review': project / 'work/sync_anchor_review.json'}


def validate(project, paths, maximum_offset_seconds=1 / 60 + .002):
    matches, asr, recipe = (read_json(paths[key]) for key in ('matches', 'asr', 'recipe'))
    if asr.get('audio_sha256') != sha256(paths['audio']):
        raise ValueError('ASR does not match current processed audio; transcribe that audio again')
    words = words_from_asr(asr)
    fps = finite(recipe.get('canvas', {}).get('fps', recipe.get('fps', 60)), 'fps')
    if fps != 60:
        raise ValueError('Current template requires a 60fps recipe; do not reuse 30fps frame numbers')
    if not 0 <= maximum_offset_seconds <= 1 / fps + .002:
        raise ValueError('Offset tolerance must not exceed one output frame plus 2ms rounding tolerance')
    review = read_json(paths['review']) if paths['review'].is_file() else {}
    review_current = (review.get('audio_sha256') == sha256(paths['audio']) and
                      review.get('asr_sha256') == sha256(paths['asr']))
    recipe_shots = recipe.get('shots', [])
    ids = [str(s.get('id')) for s in recipe_shots]
    if len(ids) != len(set(ids)):
        raise ValueError('Duplicate IDs in render recipe')
    by_id = {str(s.get('id')): s for s in recipe_shots}
    selected = matches.get('shots', [])
    selected_ids = [str(s.get('id')) for s in selected]
    expected_body = [value for value in ids if value.startswith('S')]
    actual_body = [value for value in selected_ids if value.startswith('S')]
    failures, measurements, warnings = [], [], []
    if len(selected_ids) != len(set(selected_ids)) or expected_body != actual_body or not expected_body:
        failures.append({'id': '*', 'reason': 'body_IDs_missing_duplicate_or_out_of_order'})
    previous_frame, previous_word = -1, -1
    for shot in selected:
        shot_id = str(shot.get('id', '?'))
        if not shot_id.startswith('S'):
            continue  # Hook/brand use dedicated intro validators and different entry semantics.
        anchor = None
        try:
            candidates = occurrences(words, shot.get('visual_anchor_text', ''))
            if not candidates:
                raise ValueError('anchor_not_found_in_actual_ASR')
            occurrence = shot.get('anchor_occurrence')
            if len(candidates) > 1 and (type(occurrence) is not int or not 1 <= occurrence <= len(candidates)):
                raise ValueError('ambiguous_anchor: set explicit 1-based anchor_occurrence after checking context')
            if occurrence is not None and (type(occurrence) is not int or not 1 <= occurrence <= len(candidates)):
                raise ValueError('invalid_anchor_occurrence')
            anchor = candidates[(occurrence or 1) - 1]
            if not anchor['at_word_boundary']:
                raise ValueError('anchor_starts_inside_ASR_token: follow bounded recovery in quality-review.md')
            current_frame = finite(shot.get('startFrame'), 'matches.startFrame')
            if current_frame != int(current_frame) or current_frame <= previous_frame:
                raise ValueError('invalid_or_non_monotonic_frame')
            if anchor['word_index'] <= previous_word:
                raise ValueError('anchor_words_not_in_narration_order')
            render = by_id.get(shot_id)
            if render is None:
                raise ValueError('shot_missing_from_render_recipe')
            render_seconds = finite(render.get('start_seconds'), 'recipe.start_seconds')
            if abs(render_seconds - current_frame / fps) > 1e-5:
                raise ValueError('recipe_and_matches_cut_times_disagree')
            if 'startFrame' in render and finite(render['startFrame'], 'recipe.startFrame') != current_frame:
                raise ValueError('recipe_frame_number_disagrees')
            if 'start_seconds' in shot and abs(finite(shot['start_seconds'], 'matches.start_seconds') - render_seconds) > 1e-5:
                raise ValueError('matches_frame_and_seconds_disagree')
            offset = render_seconds - anchor['start']
            if abs(offset) > maximum_offset_seconds:
                raise ValueError(f'actual_word_cut_offset:{offset:.6f}s')
            if 'visual_anchor_source_start' in shot and abs(finite(shot['visual_anchor_source_start'], 'claimed_source_start') - anchor['start']) > maximum_offset_seconds:
                raise ValueError('claimed_anchor_start_disagrees_with_current_ASR')
            probability = anchor['minimum_probability']
            if probability is None or probability < .6:
                evidence = review.get('anchors', {}).get(shot_id, {}) if review_current else {}
                if not (evidence.get('word_index') == anchor['word_index'] and
                        evidence.get('confirmed') is True and str(evidence.get('notes', '')).strip() and
                        evidence.get('basis') in {'audio_analysis', 'waveform_and_transcript', 'alternate_alignment'}):
                    raise ValueError('low_confidence_anchor_requires_current_evidence_review')
                warnings.append({'id': shot_id, 'reason': 'Reviewed ASR estimate; acoustic accuracy is not guaranteed to one frame'})
            measurements.append({'id': shot_id, **anchor, 'render_start_seconds': render_seconds,
                                 'measured_offset_seconds': offset, 'reported_offset_ignored': shot.get('visual_anchor_offset_seconds')})
            previous_frame, previous_word = current_frame, anchor['word_index']
        except (ValueError, TypeError) as exc:
            failure = {'id': shot_id, 'reason': str(exc)}
            if anchor is not None:
                failure['anchor_evidence'] = anchor  # Diagnostic estimate, never a passing measurement.
            failures.append(failure)
    offsets = [item['measured_offset_seconds'] for item in measurements]
    checks = {'shots_exist': bool(expected_body), 'all_shots_have_measured_anchors': len(measurements) == len(expected_body),
              'all_anchor_offsets_within_limit': not failures,
              'offsets_recomputed_from_current_ASR': True, 'render_recipe_checked': True}
    return {'schema_version': 2, 'passed': all(checks.values()), 'created_at': now(),
            **{key: str(paths[key]) for key in ('matches', 'asr', 'audio', 'recipe')},
            **{key + '_sha256': sha256(paths[key]) for key in ('matches', 'asr', 'audio', 'recipe')},
            'anchor_review_sha256': sha256(paths['review']) if paths['review'].is_file() else None,
            'fps': fps, 'maximum_offset_seconds': maximum_offset_seconds,
            'observed_maximum_absolute_offset_seconds': max(map(abs, offsets), default=None),
            'shot_count': len(expected_body), 'checks': checks, 'measurements': measurements,
            'warnings': warnings, 'failures': failures,
            'limitation': 'Agreement with ASR estimates and recipe; not independent pixel recognition of every cut.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('project_dir', type=Path)
    for name in ('matches', 'asr', 'audio', 'recipe', 'output'):
        parser.add_argument('--' + name, type=Path)
    parser.add_argument('--maximum-offset-seconds', type=float, default=1 / 60 + .002)
    args = parser.parse_args()
    project = args.project_dir.resolve()
    output = args.output or project / 'work/narration_image_sync_validation.json'
    try:
        paths = inputs(project, args.matches, args.asr, args.audio, args.recipe)
        report = validate(project, paths, args.maximum_offset_seconds)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        report = {'schema_version': 2, 'passed': False, 'created_at': now(), 'failures': [{'reason': str(exc)}]}
    write_json(output, report)
    print(__import__('json').dumps(report, ensure_ascii=False))
    return 0 if report['passed'] else 2


if __name__ == '__main__':
    raise SystemExit(main())
