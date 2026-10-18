"""Regression checks using isolated files and actual FFmpeg remuxes (no paid services)."""
from __future__ import annotations

import importlib.util
import json
import math
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

import production_workflow as workflow
from validation_cache import (dependency, now, read_json, receipt_path, seal, sha256,
                              snapshot, valid_receipt, verify_reused_report,
                              video_fingerprint, write_json)


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='life-skill-evidence-')
        self.root = Path(self.temp.name)
        self.source = self.root / 'source.txt'
        self.source.write_text('one', encoding='utf-8')
        self.report = self.root / 'report.json'
        write_json(self.report, {'passed': True})
        self.deps = [dependency(self.source)]
        self.current = snapshot(self.deps, {'mode': 'machine_only'})
        seal(self.report, self.current)

    def tearDown(self):
        self.temp.cleanup()

    def test_status_keeps_failure_reason_without_cache(self):
        report = self.root / 'work' / workflow.REPORTS['sync']
        write_json(report, {'passed': False, 'failures': [{'id': 'S003', 'reason': 'cut offset'}]})
        value = workflow.status(self.root)['sync']
        self.assertTrue(value.startswith('检查失败'))
        self.assertIn('S003', value)
        self.assertIn('cut offset', value)

    def test_delivery_status_does_not_require_a_cache(self):
        report = self.root / 'work' / workflow.REPORTS['delivery']
        write_json(report, {'passed': True, 'source': str(self.source), 'source_sha256': sha256(self.source)})
        self.assertIn('上次交付检查通过', workflow.status(self.root)['delivery'])
        self.assertFalse(receipt_path(report).exists())
        self.source.write_text('changed video', encoding='utf-8')
        self.assertIn('输入已变化', workflow.status(self.root)['delivery'])


    def test_status_missing_and_broken_reports_are_distinct(self):
        self.assertEqual(workflow.status(self.root)['images'], '待执行')
        report = self.root / 'work' / workflow.REPORTS['images']
        report.parent.mkdir(exist_ok=True)
        report.write_text('not json', encoding='utf-8')
        self.assertEqual(workflow.status(self.root)['images'], '失败：报告损坏')

    def test_unchanged_evidence_valid(self):
        self.assertIsNotNone(valid_receipt(self.report))

    def test_input_change_invalidates(self):
        self.source.write_text('two', encoding='utf-8')
        self.assertIsNone(valid_receipt(self.report))

    def test_report_tamper_invalidates(self):
        write_json(self.report, {'passed': True, 'fake': 'new report'})
        self.assertIsNone(valid_receipt(self.report))

    def test_parameter_change_invalidates(self):
        self.assertIsNone(valid_receipt(self.report, snapshot(self.deps, {'mode': 'listening'})))

    def test_checker_version_change_invalidates(self):
        receipt = read_json(receipt_path(self.report))
        receipt['snapshot']['toolchain']['schema'] = -1
        write_json(receipt_path(self.report), receipt)
        self.assertIsNone(valid_receipt(self.report))

    def test_old_report_cannot_be_rebound_without_receipt(self):
        write_json(self.report, {'passed': True, 'evidence_reuse': {'reused_at': now()}})
        receipt_path(self.report).unlink()
        self.assertFalse(verify_reused_report(self.report))

    def test_prepare_preserves_existing_human_record(self):
        work = self.root / 'work'
        work.mkdir()
        record = work / '制作执行记录.md'
        record.write_text('真实审核记录，不能覆盖', encoding='utf-8')
        before = record.read_bytes()
        workflow.prepare(self.root)
        workflow.prepare(self.root)
        self.assertEqual(record.read_bytes(), before)

    def test_motion_plan_refuses_to_guess_and_preserves_existing(self):
        row = '| S001 | 旁白 | 锚点 | 任务 | 场景 | 布局 | 中心 | 推近 | 无文字 | image.png | 已生成 |'
        (self.root / '03_分镜表.md').write_text(row, encoding='utf-8')
        with self.assertRaises(ValueError):
            workflow.prepare(self.root, motion_plan=True)
        path = self.root / '06_正文运动.json'
        self.assertFalse(path.exists())
        (self.root / '03_分镜表.md').write_text(row.replace('中心', '[0.25,0.4]'), encoding='utf-8')
        workflow.prepare(self.root, motion_plan=True)
        self.assertEqual(read_json(path)['shots']['S001']['focus_x'], .25)
        before = path.read_bytes()
        workflow.prepare(self.root, motion_plan=True)
        self.assertEqual(before, path.read_bytes())

    def test_failed_sync_never_becomes_cached_pass(self):
        work = self.root / 'work'
        work.mkdir(exist_ok=True)
        audio = work / 'voice.wav'
        audio.write_bytes(b'isolated alignment binding fixture')
        write_json(work / 'asr_processed.json', {'audio_sha256': sha256(audio), 'segments': [{'words': [
            {'text': '你出门', 'start': 1., 'end': 2., 'probability': .99}]}]})
        write_json(work / 'recipe.json', {'voice': str(audio), 'canvas': {'fps': 60},
            'shots': [{'id': 'S001', 'startFrame': 90, 'start_seconds': 1.5}]})
        write_json(work / 'matches.json', {'shots': [{'id': 'S001', 'startFrame': 1,
                   'visual_anchor_text': '你出门', 'visual_anchor_offset_seconds': .5}]})
        first = workflow.run_check(self.root, 'sync')
        self.assertEqual(first['status'], '失败')
        self.assertFalse(receipt_path(work / 'narration_image_sync_validation.json').exists())
        data = read_json(work / 'matches.json')
        data['shots'][0]['visual_anchor_offset_seconds'] = 0
        data['shots'][0]['startFrame'] = 60
        write_json(work / 'matches.json', data)
        recipe = read_json(work / 'recipe.json')
        recipe['shots'][0].update(startFrame=60, start_seconds=1.)
        write_json(work / 'recipe.json', recipe)
        second = workflow.run_check(self.root, 'sync')
        self.assertEqual(second['status'], '机器通过')
        third = workflow.run_check(self.root, 'sync')
        self.assertEqual(third['action'], '复用有效证据')


    def test_cached_asr_avoids_loading_recognition_model(self):
        import transcribe_voice
        output = self.root / 'asr.json'
        models = self.root / 'models'
        models.mkdir()
        (models / 'model.bin').write_bytes(b'isolated cache test fixture')
        params = {'model': 'small', 'language': 'zh', 'beam_size': 5, 'best_of': 5,
                  'word_timestamps': True, 'vad_filter': True,
                  'vad_parameters': {'min_silence_duration_ms': 100},
                  'condition_on_previous_text': True, 'device': 'cpu', 'compute_type': 'int8'}
        write_json(output, {'audio_sha256': sha256(self.source), 'segments': [{'text': '你好'}]})
        seal(output, snapshot([dependency(self.source), dependency(models, 'tree')], params))
        with patch.object(sys, 'argv', ['transcribe_voice.py', str(self.source), str(output),
                                        '--model-dir', str(models)]):
            self.assertEqual(transcribe_voice.main(), 0)



@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg tools required')
class RemuxTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='life-skill-remux-')
        cls.root = Path(cls.temp.name)
        cls.work = cls.root / 'work'
        cls.work.mkdir()
        cls.ffmpeg = Path(shutil.which('ffmpeg'))
        cls.ffprobe = Path(shutil.which('ffprobe'))
        cls.source = cls.work / 'remix.mp4'
        write_json(cls.root / '00_项目配置.json', {'title': 'isolated test',
            'intro': {'fps': 60, 'duration_frames': 120, 'cold_hook': {'enabled': False}}})
        cls.call('-f', 'lavfi', '-i', 'testsrc2=size=640x360:rate=60', '-t', '3',
                 '-c:v', 'libx264', '-preset', 'ultrafast', '-pix_fmt', 'yuv420p', str(cls.source))
        cls.changed_audio = cls.root / 'remux-with-audio.mp4'
        cls.call('-i', str(cls.source), '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=48000',
                 '-map', '0:v:0', '-map', '1:a:0', '-c:v', 'copy', '-c:a', 'aac', '-t', '3', str(cls.changed_audio))
        cls.time_shift = cls.root / 'shift.mp4'
        cls.call('-itsoffset', '1', '-i', str(cls.source), '-c:v', 'copy', '-copyts', str(cls.time_shift))

    @classmethod
    def call(cls, *args):
        result = subprocess.run([str(cls.ffmpeg), '-hide_banner', '-loglevel', 'error', '-y', *args],
                                capture_output=True, text=True, encoding='utf-8', errors='replace')
        if result.returncode:
            raise RuntimeError(result.stderr)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_audio_remux_matches_but_timestamp_shift_does_not(self):
        original = video_fingerprint(self.source, self.ffprobe)
        self.assertEqual(original, video_fingerprint(self.changed_audio, self.ffprobe))
        self.assertNotEqual(original, video_fingerprint(self.time_shift, self.ffprobe))

    def test_recipe_audio_change_can_reuse_but_picture_change_cannot(self):
        image = self.root / 'image.png'
        image.write_bytes(b'picture one')
        write_json(self.work / 'recipe.json', {'duration': 3, 'bgm': 'a.wav',
            'shots': [{'id': 'S001', 'image_path': str(image), 'start_seconds': 0, 'end_seconds': 3}]})
        _, deps, params = workflow.spec(self.root, 'motion', self.ffmpeg)
        first = snapshot(deps, params)
        recipe = read_json(self.work / 'recipe.json')
        recipe['bgm'] = 'b.wav'
        recipe['audio_mix'] = {'plan': 'new-plan.json'}
        write_json(self.work / 'recipe.json', recipe)
        self.assertEqual(first, snapshot(deps, params))
        image.write_bytes(b'picture two')
        self.assertNotEqual(first, snapshot(deps, params))


if __name__ == '__main__':
    unittest.main(verbosity=2)
