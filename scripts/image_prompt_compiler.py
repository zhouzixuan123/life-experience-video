"""Preserve storyboard facts; attach only a scoped major-error repair directive."""
import json
from pathlib import Path

def enrich_shots(shots, project_dir, repair_ids):
    path = project_dir / 'work/image_repair_directives.json'
    data = json.loads(path.read_text(encoding='utf-8-sig')) if path.is_file() else {}
    repairs = data.get('shots', data)
    out = []
    for original in shots:
        shot = dict(original)
        shot['scene'] += ' Full-bleed 16:9 illustration. Keep the specified characters, action and composition; no generated text.'
        if shot['id'] == 'I10':
            shot['layout'] += ' Subject and prop on the left; low-detail title space on the right.'
        if shot['id'] in repair_ids:
            fix = repairs.get(shot['id'], {})
            if fix.get('repair_round', 1) != 1: raise ValueError('Only one quality-repair round is allowed')
            def text(key):
                value = fix.get(key, '')
                return '; '.join(map(str, value)) if isinstance(value, list) else str(value)
            if not text('issues').strip() or not text('required_changes').strip():
                raise ValueError('A repair needs a concrete major error and a visible correction')
            shot['scene'] += ' Local correction only: ' + text('issues') + '. Change: ' + text('required_changes')
            shot['rules'] += ' Preserve: ' + text('preserve') + '. Avoid: ' + text('avoid')
        out.append(shot)
    return out
