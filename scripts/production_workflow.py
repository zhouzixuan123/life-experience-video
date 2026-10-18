"""Prepare/resume records and run registered checks with content-bound reuse."""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

from validation_cache import (dependency, now, probe_for, read_json, receipt_path,
                              seal, sha256, snapshot, valid_receipt, write_json)

ROOT = Path(__file__).resolve().parent.parent
REPORTS = {
    'images': 'image_review_validation.json',
    'storyboard': 'storyboard_validation.json', 'sync': 'narration_image_sync_validation.json',
    'motion': 'body_motion_validation.json', 'shots': 'shot_sequence_validation.json',
    'captions': 'caption_render_validation.json',
    'voice': 'audio_input_check.json', 'delivery': 'delivery_validation.json',
}
SCRIPTS = {
    'images': 'validate_image_review.py',
    'storyboard': 'validate_storyboard_md.py', 'sync': 'validate_narration_image_sync.py',
    'motion': 'validate_body_motion.py', 'shots': 'validate_shot_sequence.py',
    'captions': 'validate_caption_render.py',
    'voice': 'validate_audio_input.py', 'delivery': 'validate_final_delivery.py',
}
VISUAL = {'motion', 'shots', 'captions'}
# Only these known audio fields are excluded; duration, fps, shots, captions and
# all unknown keys remain dependencies. Actual video packet timing is also bound.
AUDIO_RECIPE_KEYS = ['voice', 'bgm', 'audio_mix']


def local(project: Path, value) -> Path:
    path = Path(str(value))
    return path.resolve() if path.is_absolute() else (project / path).resolve()


def spec(project: Path, stage: str, ffmpeg: Path | None, audio=None, asr=None,
         mode='machine_only', review=None) -> tuple[list[str], list[dict], dict]:
    work = project / 'work'
    command = [sys.executable, '-B', str(ROOT / 'scripts' / SCRIPTS[stage])]
    deps = []
    params = {'stage': stage, 'version': 1}
    if stage == 'storyboard':
        command += [str(project / '03_分镜表.md'), '--project-dir', str(project)]
        deps = [dependency(project / name) for name in
                ('03_分镜表.md', '01_确认文稿.md', '00_项目配置.json')]
    else:
        command += [str(project)]
    if stage == 'sync':
        from validate_narration_image_sync import inputs
        paths = inputs(project, audio=audio, asr=asr)
        command += ['--audio', str(paths['audio']), '--asr', str(paths['asr'])]
        deps += [dependency(paths[key]) for key in ('matches', 'asr', 'audio', 'recipe')]
        deps += [dependency(paths['review'], 'optional')]
    if stage == 'images':
        from validate_image_review import storyboard_images
        from visual_style import resolve as resolve_style
        style = resolve_style(project)
        params['style_sha256'] = style['sha256']
        if style['reference']:
            deps += [dependency(Path(style['reference']))]
        deps += [dependency(project / '00_项目配置.json', 'optional'), dependency(ROOT / 'assets/visual-style.json'), dependency(project / '03_分镜表.md'), dependency(work / 'image_content_review.json')]
        deps += [dependency(path) for path in storyboard_images(project).values()]
        for record in read_json(work / 'image_content_review.json').get('images', {}).values():
            deps += [dependency(local(project, ref['path'])) for ref in record.get('reference_images', [])]
    if stage in VISUAL:
        if not ffmpeg or not ffmpeg.is_file():
            raise FileNotFoundError('Pass --ffmpeg with an existing executable')
        probe = probe_for(ffmpeg)
        command += ['--ffmpeg', str(ffmpeg)]
        deps += [dependency(ffmpeg), dependency(probe),
                 dependency(work / 'remix.mp4', 'video', ffprobe=str(probe))]
    if stage in {'motion', 'shots'}:
        deps += [dependency(work / 'recipe.json', 'json', exclude=AUDIO_RECIPE_KEYS)]
        recipe = read_json(work / 'recipe.json')
        # Input pictures must be unchanged too: a new image with an old render
        # must invalidate the previous audit, even when recipe paths are stable.
        for shot in recipe.get('shots', []):
            if str(shot.get('id', '')).startswith('S'):
                deps += [dependency(local(project, shot.get('image_path', '')))]
    if stage == 'shots':
        deps += [dependency(project / '03_分镜表.md')]
    if stage == 'captions':
        from font_utils import resolve_font
        deps += [dependency(work / 'captions.srt'), dependency(work / 'video_without_captions.mp4'),
                 dependency(resolve_font('bold'))]
    if stage == 'voice':
        if not audio or not asr:
            raise ValueError('voice requires --audio and --asr for the current processed voice')
        command += ['--audio', str(audio), '--asr', str(asr)]
        if mode == 'machine_only':
            command += ['--machine-only']
        review = review or work / 'audio_input_review.json'
        command += ['--review', str(review)]
        deps += [dependency(review)]
        deps += [dependency(audio), dependency(asr), dependency(project / '02_配音稿.txt')]
        params.update({'mode': mode, 'audio': str(audio), 'asr': str(asr)})
    return command, deps, params


def prepare(project: Path, motion_plan=False) -> dict:
    work = project / 'work'
    work.mkdir(parents=True, exist_ok=True)
    created = []
    for source, dest in [('execution-log-template.md', '制作执行记录.md'),
                         ('image-review-template.md', '图片查看说明.md')]:
        target = work / dest
        if not target.exists():
            shutil.copy2(ROOT / 'assets' / source, target)
            created.append(str(target))
    if motion_plan:
        target = project / '06_正文运动.json'
        if not target.exists():
            from validate_storyboard_md import EXPECTED_HEADER, cells
            shots = {}
            for line in (project / '03_分镜表.md').read_text(encoding='utf-8-sig').splitlines():
                row = cells(line) if line.lstrip().startswith('|') else []
                if len(row) != len(EXPECTED_HEADER) or not re.fullmatch(r'S\d{3}', row[0]):
                    continue
                focus = re.search(r'\[\s*([0-9.]+)\s*,\s*([0-9.]+)\s*\]', row[6])
                if not focus:
                    raise ValueError(f'{row[0]} needs explicit focus coordinates; will not guess')
                x, y = map(float, focus.groups())
                if not (0 <= x <= 1 and 0 <= y <= 1):
                    raise ValueError(f'{row[0]} focus outside 0..1')
                shots[row[0]] = {'focus_x': x, 'focus_y': y, 'subject': row[6],
                                  'motion_class': 'normal', 'visual_review_required': True}
            if not shots:
                raise ValueError('No body storyboard rows; motion plan not created')
            write_json(target, {'version': 1, 'defaults': {'type': 'push_to_subject',
                        'scale_start': 1.0, 'scale_end': 1.1}, 'shots': shots,
                        'note': '分镜焦点初稿；必须逐图核对主体位置和景别幅度后使用'})
            created.append(str(target))
    return {'created': created, 'existing_records_preserved': True}


def record(project: Path, stage: str, result: dict) -> None:
    path = project / 'work' / 'execution_state.json'
    data = read_json(path) if path.exists() else {'version': 1, 'stages': {}}
    data['stages'][stage] = result
    data['updated_at'] = now()
    write_json(path, data)
    lines = ['# 制作检查摘要', '', '自动结果不代替逐图审核或最终视听审核。实际内容结论仍填制作执行记录。', '',
             '| 检查 | 机器状态 | 证据 | 本次动作 |', '|---|---|---|---|']
    for name, item in data['stages'].items():
        lines.append(f"| {name} | {item['status']} | {item.get('report', '')} | {item.get('action', '')} |")
    (project / 'work' / '制作检查摘要.md').write_text('\n'.join(lines) + '\n', encoding='utf-8', newline='\n')


def run_check(project, stage, ffmpeg=None, audio=None, asr=None, mode='machine_only',
              review=None, force=False, memo=None) -> dict:
    command, deps, params = spec(project, stage, ffmpeg, audio, asr, mode, review)
    report = project / 'work' / REPORTS[stage]
    current = snapshot(deps, params, memo) if stage != 'delivery' else None
    old = None if force or current is None else valid_receipt(report, current)
    if old and read_json(report).get('passed') is True:
        data = read_json(report)
        if stage in VISUAL:
            # Only rebind after proving bitstream + timing + all dependencies
            # are unchanged. Do not claim a new visual inspection occurred.
            source = project / 'work' / 'remix.mp4'
            if data.get('source_sha256') != sha256(source) or (
                stage in {'motion', 'shots'} and data.get('recipe_sha256') != sha256(project / 'work' / 'recipe.json')
            ):
                data['evidence_reuse'] = {'original_checked_at': old['checked_at'],
                    'reused_at': now(), 'basis': 'identical_video_packets_timing_and_dependencies',
                    'previous_report_sha256': sha256(report)}
                data['created_at'] = now()
                data['source_sha256'] = sha256(source)
                if stage in {'motion', 'shots'}:
                    data['recipe_sha256'] = sha256(project / 'work' / 'recipe.json')
                write_json(report, data)
                seal(report, current, checked_at=old['checked_at'])
        result = {'status': '机器通过', 'action': '复用有效证据', 'report': str(report),
                  'report_sha256': sha256(report), 'content_review': '由原记录核验，未自动填写'}
    else:
        # Old failed checks are never cached as passes. Do not blindly rerun a
        # deterministic failure; leave exact repair instructions to the agent.
        receipt_path(report).unlink(missing_ok=True)
        completed = subprocess.run(command, cwd=project, capture_output=True,
                                   text=True, encoding='utf-8', errors='replace',
                                   env={**__import__('os').environ, 'PYTHONIOENCODING': 'utf-8', 'PYTHONDONTWRITEBYTECODE': '1'})
        passed = completed.returncode == 0 and report.exists() and read_json(report).get('passed') is True
        # Detect input changes while the child process was running.
        if passed and current is not None:
            after = snapshot(deps, params)
            passed = after == current
            if passed:
                auxiliary = []
                seal(report, current, auxiliary)
        result = {'status': '机器通过' if passed else '失败', 'action': '实际运行检查',
                  'report': str(report), 'report_sha256': sha256(report) if report.exists() else None,
                  'returncode': completed.returncode, 'content_review': '待实际审核',
                  'diagnostic': (completed.stderr or completed.stdout)[-2500:] if not passed else ''}
    record(project, stage, result)
    return result


def status(project: Path) -> dict:
    result = {}
    memo = {}
    for stage, filename in REPORTS.items():
        path = project / 'work' / filename
        if not path.exists():
            result[stage] = '待执行'
        else:
            try:
                data = read_json(path)
                if not isinstance(data, dict) or not isinstance(data.get('checks', {}), dict):
                    raise ValueError('Report must be an object with an optional checks object')
                if data.get('passed') is not True:
                    failed_checks = [key for key, value in data.get('checks', {}).items() if value is False]
                    detail = data.get('failures') or failed_checks or data.get('hard_failures') or '详见报告'
                    result[stage] = '检查失败：' + str(detail)[:1200]
                elif stage == 'delivery':
                    # Delivery is always executed, never cached. This is a historical
                    # result, not a claim that all transitive inputs remain current.
                    pairs = [(key, value) for key, value in data.items()
                             if key.endswith('_sha256') and isinstance(data.get(key[:-7]), str)]
                    changed = [key[:-7] for key, value in pairs
                               if not local(project, data[key[:-7]]).is_file()
                               or sha256(local(project, data[key[:-7]])) != value]
                    result[stage] = ('输入已变化：' + ', '.join(changed) if changed else
                                     '上次交付检查通过；不缓存，发布前仍须实际复检')
                elif not valid_receipt(path, memo=memo):
                    result[stage] = '证据待更新：输入或检查器已变化，或缺少有效绑定'
                elif stage == 'voice' and not (
                    data.get('content_review_current') is True
                ):
                    result[stage] = '机器音质通过；文稿差异待审核，尚不能交付'
                else:
                    result[stage] = '有效机器证据，内容审核见原记录'
            except (OSError, ValueError, TypeError):
                result[stage] = '失败：报告损坏'
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('project_dir', type=Path)
    parser.add_argument('action', choices=['prepare', 'status', 'check'])
    parser.add_argument('--stage', choices=list(REPORTS), default='delivery')
    parser.add_argument('--ffmpeg', type=Path)
    parser.add_argument('--audio', type=Path)
    parser.add_argument('--asr', type=Path)
    parser.add_argument('--review', type=Path)
    parser.add_argument('--review-mode', choices=['machine_only', 'listening'])
    parser.add_argument('--motion-plan', action='store_true')
    parser.add_argument('--force', action='store_true')
    args = parser.parse_args()
    project = args.project_dir.resolve()
    if not project.is_dir():
        parser.error('Project directory must already exist')
    try:
        if args.action == 'prepare':
            result = prepare(project, args.motion_plan)
        elif args.action == 'status':
            result = status(project)
        else:
            if args.stage == 'voice' and args.review_mode is None:
                parser.error('voice requires explicit --review-mode based on actual listening capability')
            stages = [args.stage]
            result = {}
            memo = {}
            for stage in stages:
                result[stage] = run_check(project, stage,
                    args.ffmpeg.resolve() if args.ffmpeg else None,
                    args.audio.resolve() if args.audio else None,
                    args.asr.resolve() if args.asr else None, args.review_mode or 'machine_only',
                    args.review.resolve() if args.review else None, args.force, memo)
                if result[stage]['status'] == '失败':
                    print(json.dumps(result, ensure_ascii=False))
                    return 2
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        if args.action == 'check':
            record(project, args.stage, {'status': '失败', 'action': '输入或执行错误',
                                         'report': '', 'diagnostic': str(exc)})
        print(json.dumps({'status': '失败', 'reason': str(exc)}, ensure_ascii=False))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
