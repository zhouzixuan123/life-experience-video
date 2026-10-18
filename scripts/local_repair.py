"""Prepare bounded repair plans and atomically install one replacement picture."""
from __future__ import annotations

import argparse
import shutil
from pathlib import Path

from PIL import Image
from validate_image_review import storyboard_images
from validation_cache import now, read_json, sha256, write_json

ROOT = Path(__file__).resolve().parent.parent


def install_image(project, shot_id, source, apply=False):
    images = storyboard_images(project)
    if shot_id not in images:
        raise ValueError('Unknown storyboard shot: ' + shot_id)
    target = images[shot_id]
    if not target.is_relative_to(project.resolve()):
        raise ValueError('Replacement target must be inside this episode; shared or other-project assets cannot be overwritten')
    with Image.open(source) as image:
        image.load()
        width, height = image.size
        expected = {'.png': 'PNG', '.jpg': 'JPEG', '.jpeg': 'JPEG'}.get(target.suffix.lower())
        if expected != image.format:
            raise ValueError('Replacement format must match target extension; no implicit conversion')
    if abs(width / height - 16 / 9) > .015 or width < 1920 or height < 1080:
        raise ValueError('Replacement must be 16:9 and at least 1920x1080')
    digest = sha256(source)
    previous = sha256(target) if target.is_file() else None
    affected = [shot_id]
    ids = list(images)
    index = ids.index(shot_id)
    for neighbor in ids[max(0, index - 1):index + 2]:
        if neighbor[0] == shot_id[0] and neighbor not in affected:
            affected.append(neighbor)
    plan = {'action': 'install_image', 'shot': shot_id, 'source': str(source), 'target': str(target),
            'source_sha256': digest, 'previous_sha256': previous, 'affected_visual_reviews': affected,
            'next_steps': ['运行 validate_image_review.py <项目目录> --prepare，读取 refresh.pending_ids',
                           '重新查看目标图及待审核相邻图，在当前绑定下更新观察', '核对主体焦点', '重建受影响画面',
                           '核对 images 记录；实际查看受影响成片位置', '当前成片审核和最终交付检查'],
            'applied': False}
    if not apply or digest == previous:
        return plan
    work = project / 'work'
    review_path = work / 'image_content_review.json'
    review = read_json(review_path) if review_path.is_file() else None
    old_review = review_path.read_bytes() if review_path.is_file() else None
    archive = work / 'archive/rollback'
    archive.mkdir(parents=True, exist_ok=True)
    backup = archive / f'image-{shot_id}{target.suffix}'
    pending = target.with_name(target.stem + '.pending' + target.suffix)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_file():
        shutil.copy2(target, backup)
    if old_review is not None:
        (archive / f'image-{shot_id}-review.json').write_bytes(old_review)
    try:
        shutil.copy2(source, pending)
        if sha256(pending) != digest:
            raise ValueError('Source changed during installation')
        pending.replace(target)
        if review is not None:
            for key in affected:
                item = review.get('images', {}).get(key)
                if item is not None:
                    item['actual_viewed'] = False
                    item['result'] = 'pending'
                    item['invalidated_at'] = now()
                    item['invalidation_reason'] = f'image {shot_id} replaced; recheck continuity'
                    if key == shot_id:
                        item['image_sha256'] = digest
            write_json(review_path, review)
        plan.update({'applied': True, 'applied_at': now(), 'rollback_image': str(backup) if previous else None})
        write_json(work / 'local_repair_result.json', plan)
    except Exception:
        if previous is not None:
            shutil.copy2(backup, target)
        elif target.exists():
            target.unlink()
        if old_review is not None:
            review_path.write_bytes(old_review)
        raise
    finally:
        pending.unlink(missing_ok=True)
    return plan


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('project_dir', type=Path)
    parser.add_argument('action', choices=['image'])
    parser.add_argument('--id', required=True)
    parser.add_argument('--source', type=Path)
    parser.add_argument('--apply', action='store_true', help='Install the one image; default is plan only')
    args = parser.parse_args()
    project = args.project_dir.resolve()
    try:
        if args.source is None:
            parser.error('image requires --source')
        result = install_image(project, args.id, args.source.resolve(), args.apply)
        print(__import__('json').dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(__import__('json').dumps({'passed': False, 'reason': str(exc)}, ensure_ascii=False))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
