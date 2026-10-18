"""Isolated regression tests for measured timing, visual evidence and local repair."""
from __future__ import annotations

import math
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image
import validation_cache as cache
import validate_narration_image_sync as sync
import validate_image_review as pictures
import local_repair
import enforce_single_line_captions as captions


class QualityContracts(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='life-quality-')
        self.root = Path(self.temp.name)
        self.work = self.root / 'work'
        self.work.mkdir()
        self.audio = self.work / 'voice.wav'
        self.audio.write_bytes(b'text-to-time fixture; not a real speech recognition test')
        self.words = [{'text': '你出门', 'start': 1., 'end': 1.8, 'probability': .95},
                      {'text': '他回家', 'start': 2., 'end': 2.8, 'probability': .95}]
        self.recipe = {'voice': str(self.audio), 'canvas': {'fps': 60}, 'shots': [
            {'id': 'S001', 'startFrame': 60, 'start_seconds': 1.},
            {'id': 'S002', 'startFrame': 120, 'start_seconds': 2.}]}
        self.matches = {'shots': [
            {'id': 'S001', 'startFrame': 60, 'visual_anchor_text': '你出门', 'visual_anchor_offset_seconds': 0},
            {'id': 'S002', 'startFrame': 120, 'visual_anchor_text': '他回家', 'visual_anchor_offset_seconds': 0}]}
        self.save_sync()

    def tearDown(self):
        self.temp.cleanup()

    def save_sync(self):
        cache.write_json(self.work / 'asr_processed.json', {'audio_sha256': cache.sha256(self.audio),
                         'segments': [{'words': self.words}]})
        cache.write_json(self.work / 'recipe.json', self.recipe)
        cache.write_json(self.work / 'matches.json', self.matches)

    def validate_sync(self):
        return sync.validate(self.root, sync.inputs(self.root))

    def test_real_word_times_pass(self):
        self.assertTrue(self.validate_sync()['passed'])

    def test_false_zero_cannot_hide_half_second_delay(self):
        self.recipe['shots'][0].update(startFrame=90, start_seconds=1.5)
        self.matches['shots'][0]['startFrame'] = 90
        self.save_sync()
        report = self.validate_sync()
        self.assertFalse(report['passed'])
        self.assertIn('actual_word_cut_offset', str(report['failures']))

    def test_recipe_cut_disagrees_with_matches(self):
        self.recipe['shots'][0]['start_seconds'] = 1.1
        self.save_sync()
        self.assertFalse(self.validate_sync()['passed'])

    def test_repeated_anchor_requires_explicit_occurrence(self):
        self.words[1]['text'] = '你出门'
        self.matches['shots'][1]['visual_anchor_text'] = '你出门'
        self.save_sync()
        self.assertFalse(self.validate_sync()['passed'])
        for index, shot in enumerate(self.matches['shots'], 1):
            shot['anchor_occurrence'] = index
        self.save_sync()
        self.assertTrue(self.validate_sync()['passed'])

    def test_mid_token_does_not_get_invented_timestamp(self):
        self.matches['shots'][0]['visual_anchor_text'] = '出门'
        self.save_sync()
        self.assertIn('inside_ASR_token', str(self.validate_sync()['failures']))

    def test_nan_timestamps_rejected(self):
        self.words[0]['start'] = math.nan
        self.save_sync()
        with self.assertRaises(ValueError):
            self.validate_sync()

    def test_30fps_recipe_rejected(self):
        self.recipe['canvas']['fps'] = 30
        self.save_sync()
        with self.assertRaises(ValueError):
            self.validate_sync()

    def test_low_confidence_needs_bound_observation(self):
        self.words[0]['probability'] = .2
        self.save_sync()
        report = self.validate_sync()
        self.assertFalse(report['passed'])
        evidence = next(item for item in report['failures'] if item['id'] == 'S001')['anchor_evidence']
        self.assertEqual(evidence['word_index'], 0)
        self.assertEqual(evidence['start'], 1.)
        review = {'audio_sha256': cache.sha256(self.audio),
                  'asr_sha256': cache.sha256(self.work / 'asr_processed.json'),
                  'anchors': {'S001': {'word_index': 0, 'confirmed': True,
                                      'basis': 'waveform_and_transcript', 'notes': '测试边界证据，非真实试听'}}}
        cache.write_json(self.work / 'sync_anchor_review.json', review)
        self.assertTrue(self.validate_sync()['passed'])
        review['asr_sha256'] = 'stale'
        cache.write_json(self.work / 'sync_anchor_review.json', review)
        self.assertFalse(self.validate_sync()['passed'])

    def test_wrong_audio_binding_rejected(self):
        self.audio.write_bytes(b'changed audio')
        with self.assertRaises(ValueError):
            self.validate_sync()

    def test_caption_split_uses_word_time_not_equal_duration(self):
        cues = [{'text': '你出门他回家', 'start': 1., 'end': 4.}]
        words = [{'text': '你出门', 'start': 1., 'end': 1.8, 'probability': .95},
                 {'text': '他回家', 'start': 2.7, 'end': 3.8, 'probability': .95}]
        with patch.object(captions, 'split_caption_text', return_value=['你出门', '他回家']):
            result = captions.normalize_cues(cues, 3, words)
            self.assertEqual(result[0]['end'], 2.7)
            self.assertEqual(result[1]['start'], 2.7)
            with self.assertRaises(ValueError):
                captions.normalize_cues(cues, 3)

    def test_short_caption_keeps_original_timing(self):
        cue = {'text': '你出门', 'start': 1., 'end': 1.02}
        self.assertEqual(captions.normalize_cues([cue], 15), [cue])

    def create_pictures(self, count=2):
        paths = {}
        for key, color in [('S001', 'red'), ('S002', 'blue'), ('S003', 'yellow'), ('S004', 'purple')][:count]:
            path = self.root / f'{key}.png'
            Image.new('RGB', (1920, 1080), color).save(path)
            paths[key] = path
        ref = self.root / 'character-reference.png'
        Image.new('RGB', (64, 64), 'green').save(ref)
        rows = ['| ' + ' | '.join([key, '旁白', '锚点', '任务', '场景', '构图', '[0.5,0.5]', '推近', '无文字', str(path), '已生成']) + ' |'
                for key, path in paths.items()]
        (self.root / '03_分镜表.md').write_text('\n'.join(rows), encoding='utf-8')
        pictures.prepare(self.root)
        record_path = self.work / 'image_content_review.json'
        data = cache.read_json(record_path)
        # Synthetic records exercise the validator; these solid pictures are not
        # production artwork and this test does not claim visual perception.
        for item in data['images'].values():
            item.update(actual_viewed=True, result='pass', subject_presence='people',
                        reviewer='isolated test fixture', reviewed_at=cache.now(),
                        reference_images=[{'path': str(ref), 'sha256': cache.sha256(ref)}])
            item['style_consistent'] = True
        cache.write_json(record_path, data)
        return paths, record_path

    def test_progress_edit_preserves_picture_observations(self):
        _, records = self.create_pictures()
        before = cache.read_json(records)['images']
        storyboard = self.root / '03_分镜表.md'
        storyboard.write_text(storyboard.read_text(encoding='utf-8').replace('已生成', '已审核') + '\n进度说明变化\n', encoding='utf-8')
        self.assertTrue(pictures.validate(self.root)['passed'])
        pictures.prepare(self.root)
        self.assertEqual(before, cache.read_json(records)['images'])

    def test_visual_edit_invalidates_only_shot_and_neighbors(self):
        _, records = self.create_pictures(count=4)
        storyboard = self.root / '03_分镜表.md'
        storyboard.write_text(storyboard.read_text(encoding='utf-8').replace('| 场景 |', '| 改变的动作场景 |', 1), encoding='utf-8')
        report = pictures.validate(self.root)
        self.assertEqual({row['id'] for row in report['failures']}, {'S001', 'S002'})
        pictures.prepare(self.root)
        data = cache.read_json(records)
        self.assertEqual(data['refresh']['pending_ids'], ['S001', 'S002'])
        self.assertEqual(data['images']['S003']['result'], 'pass')
        self.assertEqual(data['images']['S004']['result'], 'pass')
        self.assertFalse(pictures.validate(self.root)['passed'])

    def test_shared_character_change_requires_all_reviews(self):
        _, records = self.create_pictures()
        storyboard = self.root / '03_分镜表.md'
        storyboard.write_text(storyboard.read_text(encoding='utf-8') + '\n## B. 角色\n| C01 | 外观已变 |\n', encoding='utf-8')
        pictures.prepare(self.root)
        self.assertEqual(cache.read_json(records)['refresh']['pending_ids'], ['S001', 'S002'])

    def test_reference_change_invalidates_only_its_users(self):
        _, records = self.create_pictures(count=4)
        ref = self.root / 'other-reference.png'
        Image.new('RGB', (64, 64), 'black').save(ref)
        data = cache.read_json(records)
        for key in ('S003', 'S004'):
            data['images'][key]['reference_images'] = [{'path': str(ref), 'sha256': cache.sha256(ref)}]
        cache.write_json(records, data)
        Image.new('RGB', (64, 64), 'white').save(ref)
        pictures.prepare(self.root)
        self.assertEqual(cache.read_json(records)['refresh']['pending_ids'], ['S003', 'S004'])

    def test_incompatible_records_are_not_silently_approved(self):
        _, records = self.create_pictures()
        data = cache.read_json(records)
        data['schema_version'] = 1
        cache.write_json(records, data)
        pictures.prepare(self.root)
        self.assertFalse(pictures.validate(self.root)['passed'])
        self.assertEqual(cache.read_json(records)['refresh']['pending_ids'], ['S001', 'S002'])

    def test_refresh_removed_shot_keeps_rollback(self):
        _, records = self.create_pictures()
        storyboard = self.root / '03_分镜表.md'
        storyboard.write_text(storyboard.read_text(encoding='utf-8').splitlines()[0], encoding='utf-8')
        pictures.prepare(self.root)
        data = cache.read_json(records)
        self.assertEqual(data['refresh']['removed_ids'], ['S002'])
        self.assertNotIn('S002', data['images'])
        backup = cache.read_json(self.work / 'archive/rollback/image-review-before-refresh.json')
        self.assertIn('S002', backup['images'])

    def test_picture_evidence_accepts_occlusion_but_rejects_missing_rows(self):
        _, records = self.create_pictures()
        self.assertTrue(pictures.validate(self.root)['passed'])
        data = cache.read_json(records)
        del data['images']['S002']
        cache.write_json(records, data)
        self.assertFalse(pictures.validate(self.root)['passed'])

    def test_repeated_refresh_does_not_overwrite_reference_failure_rollback(self):
        _, records = self.create_pictures()
        Image.new('RGB', (64, 64), 'white').save(self.root / 'character-reference.png')
        pictures.prepare(self.root)
        backup = self.work / 'archive/rollback/image-review-before-refresh.json'
        before = backup.read_bytes()
        pictures.prepare(self.root)
        self.assertEqual(backup.read_bytes(), before)
        self.assertEqual(cache.read_json(records)['refresh']['pending_ids'], ['S001', 'S002'])

    def test_picture_or_reference_change_invalidates_review(self):
        paths, _ = self.create_pictures()
        Image.new('RGB', (1920, 1080), 'yellow').save(paths['S001'])
        self.assertFalse(pictures.validate(self.root)['passed'])

    def test_character_reference_change_invalidates_review(self):
        self.create_pictures()
        Image.new('RGB', (64, 64), 'yellow').save(self.root / 'character-reference.png')
        self.assertFalse(pictures.validate(self.root)['passed'])

    def test_failed_metadata_update_rolls_image_back(self):
        paths, records = self.create_pictures()
        before_image, before_review = paths['S001'].read_bytes(), records.read_bytes()
        replacement = self.root / 'candidate.png'
        Image.new('RGB', (1920, 1080), 'yellow').save(replacement)
        with patch.object(local_repair, 'write_json', side_effect=OSError('simulated disk failure')):
            with self.assertRaises(OSError):
                local_repair.install_image(self.root, 'S001', replacement, True)
        self.assertEqual(paths['S001'].read_bytes(), before_image)
        self.assertEqual(records.read_bytes(), before_review)

    def test_local_image_install_only_changes_target_and_invalidates_neighbors(self):
        paths, records = self.create_pictures()
        other_hash = cache.sha256(paths['S002'])
        previous_hash = cache.sha256(paths['S001'])
        replacement = self.root / 'new.png'
        Image.new('RGB', (1920, 1080), 'yellow').save(replacement)
        plan = local_repair.install_image(self.root, 'S001', replacement)
        self.assertFalse(plan['applied'])
        self.assertEqual(cache.sha256(paths['S001']), previous_hash)
        result = local_repair.install_image(self.root, 'S001', replacement, True)
        self.assertTrue(result['applied'])
        self.assertEqual(cache.sha256(paths['S002']), other_hash)
        self.assertEqual(cache.sha256(Path(result['rollback_image'])), previous_hash)
        self.assertEqual(cache.read_json(records)['images']['S002']['result'], 'pending')

    def test_local_image_install_rejects_foreign_target(self):
        paths, _ = self.create_pictures()
        with patch.object(local_repair, 'storyboard_images', return_value={'S001': self.root.parent / 'foreign.png'}):
            with self.assertRaises(ValueError):
                local_repair.install_image(self.root, 'S001', paths['S002'], True)

    def test_markdown_export_preserves_manual_notes(self):
        self.create_pictures()
        target = self.work / '图片审核记录.md'
        target.write_text('原有手写结论不得覆盖\n', encoding='utf-8')
        pictures.export_markdown(self.root)
        pictures.export_markdown(self.root)
        self.assertTrue(target.read_text(encoding='utf-8').startswith('原有手写结论不得覆盖'))
        self.assertEqual(target.read_text(encoding='utf-8').count('image-review:auto:start'), 1)


    def test_unrelated_script_change_does_not_invalidate_ASR(self):
        scripts = self.root / 'scripts'
        scripts.mkdir()
        for name in ('transcribe_voice.py', 'validation_cache.py', 'build_cover_variants.py'):
            (scripts / name).write_text('value = 1\n', encoding='utf-8')
        with patch.object(cache, '__file__', str(scripts / 'validation_cache.py')):
            before = cache.toolchain({'model': 'small'})
            (scripts / 'build_cover_variants.py').write_text('value = 2\n', encoding='utf-8')
            self.assertEqual(before, cache.toolchain({'model': 'small'}))
            (scripts / 'transcribe_voice.py').write_text('value = 2\n', encoding='utf-8')
            self.assertNotEqual(before, cache.toolchain({'model': 'small'}))

    def test_in_process_memo_reuses_scan_but_not_changed_file(self):
        video = self.root / 'video.mp4'
        video.write_bytes(b'one')
        dep = cache.dependency(video, 'video', ffprobe='test probe')
        memo = {}
        with patch.object(cache, 'video_fingerprint', return_value='same') as scanner:
            cache.snapshot([dep], {}, memo)
            cache.snapshot([dep], {}, memo)
            self.assertEqual(scanner.call_count, 1)
            video.write_bytes(b'changed length')
            cache.snapshot([dep], {}, memo)
            self.assertEqual(scanner.call_count, 2)


if __name__ == '__main__':
    unittest.main(verbosity=2)
