"""Resolve a text style and an optional user-supplied reference image."""
from pathlib import Path
from validation_cache import read_json, sha256, digest_json
ROOT = Path(__file__).resolve().parent.parent

def resolve(project):
    path = project / '00_项目配置.json'
    config = read_json(path) if path.is_file() else {}
    if 'style_lock' in config:
        raise ValueError('Use style_prompt and style_reference instead of style_lock')
    default = read_json(ROOT / 'assets/visual-style.json')
    prompt = config.get('style_prompt') or default['prompt']
    reference = config.get('style_reference') or ''
    if not isinstance(prompt, str) or not isinstance(reference, str):
        raise ValueError('style_prompt and style_reference must be strings')
    data = {'prompt': prompt, 'reference': '', 'reference_sha256': None}
    if reference:
        if not config.get('style_prompt'):
            raise ValueError('A custom reference requires its observed style_prompt')
        ref = ROOT / reference[len('skill://'):] if reference.startswith('skill://') else Path(reference)
        if not ref.is_absolute():
            ref = project / ref
        ref = ref.resolve()
        if not ref.is_file():
            raise FileNotFoundError(ref)
        data.update(reference=str(ref), reference_sha256=sha256(ref))
    return {**data, 'sha256': digest_json(data)}
