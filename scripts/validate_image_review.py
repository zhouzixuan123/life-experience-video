"""Bind per-image visual observations to current pictures; does not perform vision."""
from __future__ import annotations

import argparse
from pathlib import Path
from visual_style import resolve as resolve_style

from validation_cache import digest_json, now, read_json, sha256, write_json
from validate_storyboard_md import EXPECTED_HEADER, SHOT_ID_RE, cells


def storyboard_images(project):
    result = {}
    text = (project / '03_分镜表.md').read_text(encoding='utf-8-sig')
    for line in text.splitlines():
        row = cells(line) if line.lstrip().startswith('|') else []
        if len(row) != len(EXPECTED_HEADER) or not SHOT_ID_RE.fullmatch(row[0]):
            continue
        if row[0] in result:
            raise ValueError('Duplicate storyboard image ID: ' + row[0])
        path = Path(row[9].strip('`'))
        result[row[0]] = path.resolve() if path.is_absolute() else (project / path).resolve()
    if not result:
        raise ValueError('No fixed-template storyboard image rows')
    return result


def review_contexts(project):
    """Bind visual facts, shared character/style rules and immediate continuity.

    Ignore progress cells, timing anchors and unrelated prose. Unknown shared
    character changes conservatively affect all shots, not just a guessed cast.
    """
    rows, shared = {}, []
    section = ''
    for line in (project / '03_分镜表.md').read_text(encoding='utf-8-sig').splitlines():
        if line.startswith('## '):
            section = line
        row = cells(line) if line.lstrip().startswith('|') else []
        if len(row) == len(EXPECTED_HEADER) and SHOT_ID_RE.fullmatch(row[0]):
            rows[row[0]] = [row[index] for index in (1, 3, 4, 5, 6, 8, 9)]
        elif section.startswith(('## B.', '## E.')) and line.strip():
            shared.append(row or line.strip())
        elif row and row[0] == '画风':
            shared.append(row)
    images = storyboard_images(project)
    digests = {key: sha256(path) if path.is_file() else None for key, path in images.items()}
    ids = list(images)
    result = {}
    for index, key in enumerate(ids):
        neighbors = [other for other in ids[max(0, index - 1):index + 2]
                     if other != key and other[0] == key[0]]
        result[key] = digest_json({'style': resolve_style(project)['sha256'], 'row': rows[key], 'shared': shared,
                                  'neighbors': {other: {'row': rows[other], 'image': digests[other]}
                                                for other in neighbors}})
    return result


def prepare(project):
    path = project / 'work/image_content_review.json'
    old = read_json(path) if path.is_file() else {}
    contexts = review_contexts(project)
    records, changed = {}, []
    for key, image in storyboard_images(project).items():
        current = sha256(image) if image.is_file() else None
        item = dict(old.get('images', {}).get(key, {}))
        refs_changed = any(not _ref_current(project, ref) for ref in item.get('reference_images', []))
        invalid = (old.get('schema_version') != 3 or item.get('context_sha256') != contexts[key]
                   or item.get('image_sha256') != current or refs_changed)
        if invalid:
            if item.get('result') != 'pending' or item.get('context_sha256') != contexts[key] or item.get('image_sha256') != current:
                changed.append(key)
            item = {'image': str(image), 'image_sha256': current, 'context_sha256': contexts[key],
                    'actual_viewed': False, 'style_consistent': None, 'result': 'pending',
                    'notes': '', 'reference_images': []}
        records[key] = item
    removed = sorted(set(old.get('images', {})) - set(records))
    if path.is_file() and (changed or removed):
        backup = project / 'work/archive/rollback/image-review-before-refresh.json'
        backup.parent.mkdir(parents=True, exist_ok=True)
        backup.write_bytes(path.read_bytes())
    write_json(path, {'schema_version': 3, 'images': records,
                     'refresh': {'invalidated_ids': changed, 'removed_ids': removed,
                                 'pending_ids': [k for k, v in records.items() if v.get('result') == 'pending']}})
    return path

def _ref_current(project, ref):
    path = Path(str(ref.get('path', '')))
    if not path.is_absolute(): path = project / path
    return path.is_file() and ref.get('sha256') == sha256(path)

def validate(project):
    path = project / 'work/image_content_review.json'
    data = read_json(path)
    images = storyboard_images(project)
    contexts = review_contexts(project)
    records = data.get('images', {})
    failures = []
    if data.get('schema_version') != 3 or set(records) != set(images):
        failures.append({'id': '*', 'reason': 'prepare_current_image_list'})
    for key, image in images.items():
        item = records.get(key, {})
        reasons = []
        if not image.is_file() or item.get('image_sha256') != sha256(image): reasons.append('image_changed_or_missing')
        if item.get('context_sha256') != contexts[key]: reasons.append('visual_requirements_changed')
        if item.get('actual_viewed') is not True: reasons.append('not_viewed')
        if item.get('style_consistent') is not True: reasons.append('style_not_confirmed')
        if item.get('result') != 'pass': reasons.append('pending_or_major_error')
        if any(not _ref_current(project, ref) for ref in item.get('reference_images', [])): reasons.append('character_reference_changed')
        if reasons: failures.append({'id': key, 'reason': reasons})
    return {'schema_version': 3, 'passed': not failures, 'created_at': now(),
            'review': str(path), 'review_sha256': sha256(path), 'failures': failures,
            'expected_count': len(images), 'limitation': 'Records a brief actual visual review; does not perform vision.'}

def export_markdown(project):
    # Optional summary only; the JSON is the sole editable per-image record.
    data = read_json(project / 'work/image_content_review.json')
    pending = [key for key, item in data['images'].items() if item.get('result') != 'pass']
    target = project / 'work/图片审核记录.md'
    start, end = '<!-- image-review:auto:start -->', '<!-- image-review:auto:end -->'
    text = target.read_text(encoding='utf-8') if target.exists() else '# 图片查看摘要\n'
    import re
    text = re.sub(re.escape(start) + '.*?' + re.escape(end), '', text, flags=re.S)
    target.write_text(text.rstrip() + '\n' + start + '\n待处理：' + ', '.join(pending) + '\n' + end + '\n', encoding='utf-8')

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('project_dir', type=Path)
    parser.add_argument('--prepare', action='store_true')
    args = parser.parse_args()
    project = args.project_dir.resolve()
    try:
        if args.prepare:
            print(prepare(project)); return 0
        report = validate(project)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        report = {'passed': False, 'failures': [{'reason': str(exc)}]}
    write_json(project / 'work/image_review_validation.json', report)
    print(__import__('json').dumps(report, ensure_ascii=False))
    return 0 if report['passed'] else 2

if __name__ == '__main__':
    raise SystemExit(main())
