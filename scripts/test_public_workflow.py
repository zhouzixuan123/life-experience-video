"""Exercise the public workflow with temporary, synthetic, locally created media."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import init_episode
import production_workflow
import validate_audio_input
from build_looping_bgm_plan import build_plan
from validation_cache import read_json, sha256, write_json
from visual_style import ROOT, resolve


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg required')
class PublicWorkflow(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='public-workflow-')
        self.project = Path(self.temp.name) / 'episode'
        init_episode.initialize(self.project, '第一次值夜班')
        self.ffmpeg = Path(shutil.which('ffmpeg'))
        self.audio = self.project / '配音/narration.wav'
        self.run_ffmpeg('-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=48000',
                        '-t', '2', str(self.audio))
        (self.project / '02_配音稿.txt').write_text('示例文字', encoding='utf-8')
        self.asr = self.project / 'work/asr_processed.json'
        write_json(self.asr, {'audio_sha256': sha256(self.audio), 'segments': [
            {'words': [{'word': '示例文字', 'start': 0.1, 'end': 1.5}]}]})
        self.review = self.project / 'work/audio_input_review.json'

    def tearDown(self):
        self.temp.cleanup()

    def run_ffmpeg(self, *args):
        subprocess.run([str(self.ffmpeg), '-v', 'error', '-y', *args], check=True, capture_output=True)

    def approve_input(self):
        paths = validate_audio_input.inputs(self.project)
        validate_audio_input.prepare(paths, self.review)
        data = read_json(self.review)
        data['content_matches_script'] = True
        data['notes'] = 'Synthetic test fixture; no speech or listening assessment.'
        write_json(self.review, data)
        return paths

    def test_new_project_works_without_reference_media(self):
        cfg = read_json(self.project / '00_项目配置.json')
        self.assertEqual(cfg['voiceover']['mode'], 'user_supplied')
        self.assertEqual(resolve(self.project)['reference'], '')
        plan = build_plan(self.project, 2, self.ffmpeg, str(self.audio))
        self.assertFalse(plan['music']['enabled'])
        self.assertEqual(plan['music']['segments'], [])
        self.assertEqual(plan['sound_effects'], [])

    def test_optional_sources_loop_and_anchor_to_current_intro(self):
        cfg = read_json(self.project / '00_项目配置.json')
        cfg['intro']['cold_hook']['duration_frames'] = 30
        write_json(self.project / '00_项目配置.json', cfg)
        source = self.project / 'short-source.wav'
        self.run_ffmpeg('-f', 'lavfi', '-i', 'sine=frequency=220:sample_rate=48000',
                        '-t', '0.6', str(source))
        plan = build_plan(self.project, 2, self.ffmpeg, str(self.audio), source=source, intro_sfx=source)
        segments = plan['music']['segments']
        self.assertEqual(len(segments), 4)
        self.assertAlmostEqual(sum(item['duration'] for item in segments), 2)
        self.assertAlmostEqual(plan['sound_effects'][0]['timeline_start'], 0.5)
        self.assertEqual(plan['sound_effects'][0]['source'], str(source))

    def test_supplied_audio_requires_current_content_review(self):
        paths = validate_audio_input.inputs(self.project)
        validate_audio_input.prepare(paths, self.review)
        self.assertFalse(validate_audio_input.validate(paths, self.review)['passed'])
        self.approve_input()
        self.assertTrue(validate_audio_input.validate(paths, self.review)['passed'])
        (self.project / '02_配音稿.txt').write_text('已修改的文字', encoding='utf-8')
        self.assertFalse(validate_audio_input.validate(paths, self.review)['passed'])

    def test_unbound_transcript_is_rejected(self):
        paths = self.approve_input()
        data = read_json(self.asr)
        data['audio_sha256'] = 'wrong'
        write_json(self.asr, data)
        self.assertFalse(validate_audio_input.validate(paths, self.review)['checks']['transcript_matches_audio'])

    def test_revoked_review_invalidates_cached_input_check(self):
        self.approve_input()
        args = {'audio': self.audio, 'asr': self.asr}
        self.assertEqual(production_workflow.run_check(self.project, 'voice', **args)['status'], '机器通过')
        self.assertEqual(production_workflow.run_check(self.project, 'voice', **args)['action'], '复用有效证据')
        review = read_json(self.review)
        review['content_matches_script'] = False
        write_json(self.review, review)
        self.assertEqual(production_workflow.run_check(self.project, 'voice', **args)['status'], '失败')

    def test_narration_only_mix_creates_real_decodable_video(self):
        work = self.project / 'work'
        visual = work / 'silent_visual.mp4'
        self.run_ffmpeg('-f', 'lavfi', '-i', 'color=c=blue:s=320x180:r=60', '-t', '2',
                        '-c:v', 'libx264', '-preset', 'ultrafast', '-pix_fmt', 'yuv420p', str(visual))
        write_json(work / 'recipe.json', {'duration_seconds': 2, 'canvas': {'fps': 60}, 'bgm': 'old.wav'})
        plan = build_plan(self.project, 2, self.ffmpeg, str(self.audio))
        write_json(work / 'audio_plan.json', plan)
        result = subprocess.run([sys.executable, '-B', str(ROOT / 'scripts/compose_audio_mix.py'),
            str(self.project), str(work / 'audio_plan.json'), '--ffmpeg', str(self.ffmpeg)],
            capture_output=True, text=True, encoding='utf-8', errors='replace',
            env={**os.environ, 'PYTHONIOENCODING': 'utf-8'})
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertTrue(read_json(work / 'validation.json')['passed'])
        self.assertNotIn('bgm', read_json(work / 'recipe.json'))
        self.assertTrue((work / 'remix.mp4').is_file())
        self.assertEqual(sha256(self.audio), read_json(self.asr)['audio_sha256'])


if __name__ == '__main__':
    unittest.main()
