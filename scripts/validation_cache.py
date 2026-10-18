"""Content-bound evidence reuse; never infer success from file existence or mtime."""
from __future__ import annotations

import hashlib
import ast
import importlib.metadata
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from functools import lru_cache

SCHEMA = 2

STAGE_ENTRIES = {
    'storyboard': 'validate_storyboard_md.py', 'sync': 'validate_narration_image_sync.py',
    'motion': 'validate_body_motion.py', 'shots': 'validate_shot_sequence.py',
    'captions': 'validate_caption_render.py',
    'voice': 'validate_audio_input.py', 'images': 'validate_image_review.py',
}


@lru_cache(maxsize=128)
def imported_modules(text):
    names = set()
    for node in ast.walk(ast.parse(text)):
        if isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split('.')[0])
        elif isinstance(node, ast.Import):
            names.update(item.name.split('.')[0] for item in node.names)
    return names


def script_dependencies(parameters: dict) -> list[Path]:
    root = Path(__file__).parent
    stage = parameters.get('stage')
    entry = STAGE_ENTRIES.get(stage) or ('transcribe_voice.py' if 'model' in parameters else None)
    if entry is None:
        return sorted(root.glob('*.py'))
    pending = [root / entry, Path(__file__)]
    if stage:
        pending.append(root / 'production_workflow.py')
    result = set()
    while pending:
        file = pending.pop()
        if file in result:
            continue
        result.add(file)
        for name in imported_modules(file.read_text(encoding='utf-8-sig')):
            dep = root / (name + '.py')
            if dep.is_file() and dep not in result:
                pending.append(dep)
    return sorted(result)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def digest_json(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(',', ':')).encode('utf-8')).hexdigest()


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pending = path.with_name(path.name + '.pending')
    pending.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n',
                       encoding='utf-8', newline='\n')
    pending.replace(path)


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def dependency(path: Path, kind='file', **kwargs) -> dict:
    return {'path': str(path.resolve()), 'kind': kind, **kwargs}


def toolchain(parameters=None) -> dict:
    files = script_dependencies(parameters or {})
    imports = set()
    for file in files:
        imports.update(imported_modules(file.read_text(encoding='utf-8-sig')))
    versions = {}
    package_map = {'PIL': ['Pillow'], 'numpy': ['numpy'], 'faster_whisper': ['faster-whisper', 'ctranslate2', 'av'],
                   'opencc': ['opencc-python-reimplemented']}
    for name in sorted({pkg for module in imports for pkg in package_map.get(module, [])}):
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = None
    return {'schema': SCHEMA, 'python': sys.version, 'packages': versions,
            'scripts': {p.name: sha256(p) for p in files}}


def video_fingerprint(path: Path, ffprobe: Path) -> str:
    # Packet payload AND timing/stream properties: audio-only remuxes can reuse
    # visual evidence; changing frames, codec headers or timestamps cannot.
    result = subprocess.run([
        str(ffprobe), '-v', 'error', '-select_streams', 'v:0',
        '-show_streams', '-show_packets', '-show_data_hash', 'sha256',
        '-show_entries',
        'stream=codec_name,profile,codec_tag_string,width,height,pix_fmt,level,'
        'sample_aspect_ratio,display_aspect_ratio,color_range,color_space,color_transfer,'
        'color_primaries,field_order,extradata_hash,time_base,start_pts,duration_ts,'
        'r_frame_rate,avg_frame_rate,nb_frames:stream_side_data:'
        'packet=pts,dts,duration,size,flags,data_hash:packet_side_data',
        '-of', 'json', str(path)], capture_output=True, text=True,
        encoding='utf-8', errors='replace', timeout=180)
    if result.returncode:
        raise RuntimeError(f'Cannot fingerprint video: {result.stderr[-1000:]}')
    data = json.loads(result.stdout)
    if not data.get('streams') or not data.get('packets'):
        raise ValueError(f'No video packets: {path}')
    return digest_json(data)


def probe_for(ffmpeg: Path) -> Path:
    sibling = ffmpeg.with_name('ffprobe' + ffmpeg.suffix)
    found = sibling if sibling.is_file() else Path(shutil.which('ffprobe') or '')
    if not found.is_file():
        raise FileNotFoundError('ffprobe is required for safe visual evidence reuse')
    return found.resolve()


def snapshot(dependencies: list[dict], parameters: dict, memo=None) -> dict:
    memo = {} if memo is None else memo
    values = []
    for item in dependencies:
        path = Path(item['path'])
        # Memo is confined to this process. Changed files cannot retain a memo
        # entry merely because their pathname is unchanged.
        def identity(p):
            if not p.exists():
                return None
            stat = p.stat()
            return (stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns, stat.st_ino)
        identity_value = identity(path)
        if item['kind'] == 'tree' and path.is_dir():
            identity_value = [(str(p.relative_to(path)), identity(p)) for p in sorted(path.rglob('*')) if p.is_file()]
        key = digest_json({'dependency': item, 'identity': identity_value})
        if key not in memo:
            kind = item['kind']
            if kind == 'video':
                value = video_fingerprint(path, Path(item['ffprobe']))
            elif kind == 'json':
                value = read_json(path)
                if 'keys' in item:
                    value = {key: value.get(key) for key in item['keys']}
                else:
                    value = {key: val for key, val in value.items()
                             if key not in item.get('exclude', [])}
                value = digest_json(value)
            elif kind == 'tree':
                if not path.is_dir():
                    raise FileNotFoundError(path)
                value = digest_json({str(p.relative_to(path)): sha256(p)
                                     for p in sorted(path.rglob('*')) if p.is_file()})
            elif kind == 'optional' and not path.exists():
                value = None
            else:
                value = sha256(path)
            memo[key] = value
        values.append({'dependency': item, 'sha256': memo[key]})
    return {'dependencies': values, 'parameters': parameters, 'toolchain': toolchain(parameters)}


def receipt_path(report: Path) -> Path:
    return report.with_name(report.name + '.cache.json')


def valid_receipt(report: Path, current: dict | None = None, memo=None) -> dict | None:
    try:
        receipt = read_json(receipt_path(report))
        if receipt.get('schema') != SCHEMA or receipt.get('report_sha256') != sha256(report):
            return None
        recorded = receipt['snapshot']
        if current is None:
            current = snapshot([entry['dependency'] for entry in recorded['dependencies']],
                               recorded['parameters'], memo)
        if current != recorded:
            return None
        for item in receipt.get('auxiliary', []):
            if sha256(Path(item['path'])) != item['sha256']:
                return None
        return receipt
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        return None


def seal(report: Path, current: dict, auxiliary=(), checked_at=None) -> None:
    write_json(receipt_path(report), {
        'schema': SCHEMA, 'report_sha256': sha256(report), 'snapshot': current,
        'checked_at': checked_at or now(),
        'auxiliary': [{'path': str(p.resolve()), 'sha256': sha256(p)} for p in auxiliary]})


def verify_reused_report(report: Path, memo=None) -> bool:
    """Legacy un-reused reports still follow the original delivery checks."""
    try:
        data = read_json(report)
        if 'evidence_reuse' not in data and not receipt_path(report).exists():
            return True
        return valid_receipt(report, memo=memo) is not None
    except (OSError, ValueError, TypeError):
        return False
