"""Maintenance-only negative cases from the September production audit."""
import copy
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageFont
import init_episode
import prepare_nine_grid_intro as intro
import validate_image_review as images
import validate_final_delivery as delivery
import production_workflow as workflow
from final_media import measure
from font_utils import resolve_font
from validation_cache import read_json, write_json, sha256
from visual_style import resolve, ROOT


class Defaults(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='life-current-defaults-')
        self.project = Path(self.temp.name) / 'episode'
        init_episode.initialize(self.project, '图书管理员')

    def tearDown(self):
        self.temp.cleanup()

    def picture_records(self):
        rows=[]
        for index,key in enumerate(['H01','H02','I01','I02','I03','I04','I10','S001','S002']):
            path=self.project/'画面'/f'{key}.png'
            Image.new('RGB',(1920,1080),(index*25,40,90)).save(path)
            rows.append('| '+' | '.join([key,'测试旁白','测试旁白','借书','管理员归还书本','左侧中景','[0.3,0.5]','推近','无文字',str(path),'已生成'])+' |')
        headings=['## A. 项目信息\n图书管理员','## B. 角色与连续性锁定\n| C01 | 管理员 | 成年 | 黑发蓝衣 | 单人 | 人物一致 | 参考图 |','## C. 开头分镜',
                  *rows[:7],'## D. 正文分镜',*rows[7:],'## E. 生图统一提示词\n### 正向锚点\n\n```text\n[粘贴画风]\n```',
                  '## F. 制作统计与验收']
        from validate_storyboard_md import EXPECTED_HEADER
        headings.insert(3,'| '+' | '.join(EXPECTED_HEADER)+' |')
        (self.project/'03_分镜表.md').write_text('\n'.join(headings),encoding='utf-8')
        (self.project/'01_确认文稿.md').write_text('测试旁白',encoding='utf-8')
        records=images.prepare(self.project)
        data=read_json(records)
        for item in data['images'].values():
            item.update(actual_viewed=True,style_consistent=True,result='pass',notes='SYNTHETIC MAINTENANCE FIXTURE')
        write_json(records,data)
        return records

    def valid_intro(self):
        episode=read_json(self.project/'00_项目配置.json')
        for index,beat in enumerate(episode['intro']['cold_hook']['caption_beats']): beat['text']='测试字幕'+str(index)
        return episode

    def test_init_preserves_existing_project(self):
        path=self.project/'00_项目配置.json';before=path.read_bytes()
        with self.assertRaises(ValueError): init_episode.initialize(self.project,'另一个主题')
        self.assertEqual(before,path.read_bytes())

    def test_placeholder_style_uses_current_default_in_both_real_builders(self):
        self.picture_records()
        for name in ('chatgpt','gemini'):
            out=self.project/f'{name}.js'
            result=subprocess.run([sys.executable,'-B','-X','utf8',str(ROOT/'scripts'/f'build_{name}_f12_script.py'),
                                   str(self.project),'--output',str(out)],capture_output=True,text=True,encoding='utf-8')
            self.assertEqual(result.returncode,0,result.stderr)
            text=out.read_text(encoding='utf-8')
            self.assertIn('warm healing cartoon illustration',text)
            self.assertNotIn('pure-white oval heads, no hair',text)

    def test_false_or_missing_style_cannot_pass(self):
        path=self.picture_records();data=read_json(path)
        for value in (False,None):
            for item in data['images'].values(): item['style_consistent']=value
            write_json(path,data)
            self.assertFalse(images.validate(self.project)['passed'])

    def test_changed_style_reference_invalidates_image_reuse(self):
        path=self.picture_records()
        reference=self.project/'reference.png';Image.new('RGB',(100,100),'green').save(reference)
        cfg=read_json(self.project/'00_项目配置.json')
        cfg.update(style_prompt='soft cartoon',style_reference=str(reference))
        write_json(self.project/'00_项目配置.json',cfg)
        images.prepare(self.project);data=read_json(path)
        for item in data['images'].values():item.update(actual_viewed=True,style_consistent=True,result='pass')
        write_json(path,data)
        self.assertEqual(workflow.run_check(self.project,'images')['status'],'机器通过')
        Image.new('RGB',(100,100),'blue').save(reference)
        result=workflow.run_check(self.project,'images')
        self.assertEqual(result['status'],'失败')
        self.assertNotEqual(result['action'],'复用有效证据')

    def test_custom_reference_without_prompt_is_not_silently_defaulted(self):
        cfg=read_json(self.project/'00_项目配置.json');cfg['style_reference']='custom.png'
        write_json(self.project/'00_项目配置.json',cfg)
        with self.assertRaises(ValueError):resolve(self.project)

    def test_export_focus_coordinates_preserve_explicit_keyframes(self):
        from build_jianying_project import motion_coordinates
        result=motion_coordinates({'focus_x':.25,'focus_y':.5,'scale_start':1,'scale_end':1.1})
        self.assertEqual(result['x_start'],0)
        self.assertAlmostEqual(result['x_end'],.05)
        self.assertEqual(result['y_end'],0)
        explicit={**result,'x_end':.03}
        self.assertEqual(motion_coordinates(explicit)['x_end'],.03)

    def test_motion_parameter_cannot_make_title_early(self):
        episode=self.valid_intro();episode['intro']['source_duration_frames']=512
        episode['intro']['topic_reveal_frame']=96;episode['intro']['title_voice_start_frame']=96
        with self.assertRaises(SystemExit):intro.build_text_config(episode)

    def test_long_hook_text_is_preserved_and_fitted(self):
        episode=self.valid_intro()
        text='这条字幕有二十五个中文字需要保持原句完整而不修改文稿'
        episode['intro']['cold_hook']['caption_beats'][0]['text']=text
        episode['intro']['cold_hook']['subtitle_font_size']=84
        result=intro.build_cold_hook_config(episode)['captionBeats'][0]
        self.assertEqual(result['text'],text)
        width=ImageFont.truetype(str(resolve_font('bold')),result['fontSize']).getlength(text)
        self.assertLessEqual(width+len(text)+16,1100)


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'),'FFmpeg required')
class MediaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory(prefix='life-final-media-')
        cls.source=Path(cls.temp.name)/'sample.mp4'
        subprocess.run([shutil.which('ffmpeg'),'-v','error','-f','lavfi','-i','color=c=blue:s=1920x1080:r=60',
            '-f','lavfi','-i','sine=frequency=440:sample_rate=48000','-t','1','-c:v','libx264','-preset','ultrafast',
            '-c:a','aac',str(cls.source)],check=True,capture_output=True)

    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()

    def test_counted_frames_reject_truncated_expected_duration(self):
        report=measure(self.source,790/60)
        self.assertEqual(report['actual_frames'],60)
        self.assertFalse(report['checks']['actual_duration_matches_recipe'])

    def test_valid_short_media_passes_technical_checks(self):
        report=measure(self.source,1)
        self.assertTrue(report['passed'],report)


if __name__ == '__main__':unittest.main()
