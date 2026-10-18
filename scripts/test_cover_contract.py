"""Maintenance tests: complete titles, centered layout and independent aspect ratios."""
import tempfile
import unittest
from pathlib import Path
from PIL import Image, ImageDraw

from build_cover_variants import build_all, base_paths, cover_resize, prepare
from cover_specs import COVER_SIZES, TITLE_REGION, check_title_outputs
from validation_cache import read_json, write_json, sha256
import validate_final_delivery as delivery


class CoverContract(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='life-cover-contract-')
        self.project=Path(self.temp.name)
        self.title='你是那个替所有人扛下责任却一直被误解的班干部'
        write_json(self.project/'00_项目配置.json',{'title':self.title})
        for index,(ratio,size) in enumerate(COVER_SIZES.items()):
            path=base_paths(self.project)[ratio];path.parent.mkdir(parents=True,exist_ok=True)
            canvas=Image.new('RGB',size,(35+index*25,60,85))
            draw=ImageDraw.Draw(canvas)
            draw.rectangle((0,0,30,30),fill='red')
            draw.rectangle((size[0]-31,size[1]-31,size[0]-1,size[1]-1),fill='blue')
            canvas.save(path)

    def tearDown(self): self.temp.cleanup()

    def test_all_aspects_preserve_complete_title_and_center_block(self):
        report=build_all(self.project)
        self.assertEqual({v['ratio'] for v in report['covers']},set(COVER_SIZES))
        for item in report['covers']:
            self.assertEqual(''.join(item['title_lines']),self.title)
            w,h=item['size'];left,top,right,bottom=item['title_region']
            boxes=item['boxes']
            for box in boxes:
                self.assertGreaterEqual(box[0],left);self.assertLessEqual(box[2],right)
                self.assertGreaterEqual(box[1],top);self.assertLessEqual(box[3],bottom)
                self.assertAlmostEqual((box[0]+box[2])/2,w/2)
            self.assertAlmostEqual((boxes[0][1]+boxes[-1][3])/2,h/2)
        self.assertTrue(check_title_outputs(self.project))

    def test_abbreviated_manual_title_fails_before_overwriting_any_cover(self):
        build_all(self.project)
        before={ratio:sha256(self.project/'最终成片'/f'封面_{ratio}.jpg') for ratio in COVER_SIZES}
        config=read_json(self.project/'00_项目配置.json')
        config['covers']={'title_lines':{'3x4':['班干部']}}
        write_json(self.project/'00_项目配置.json',config)
        with self.assertRaises(ValueError):build_all(self.project)
        self.assertEqual(before,{ratio:sha256(self.project/'最终成片'/f'封面_{ratio}.jpg') for ratio in COVER_SIZES})

    def test_horizontal_source_cannot_be_used_for_portrait(self):
        bases=base_paths(self.project)
        wrong=self.project/'different-name.png'
        Image.new('RGB',(1600,1200),'orange').save(wrong)
        bases['3x4']=wrong
        with self.assertRaises(ValueError):build_all(self.project,bases)
        self.assertFalse((self.project/'最终成片').exists())

    def test_full_base_edges_are_preserved(self):
        image=cover_resize(base_paths(self.project)['3x4'],COVER_SIZES['3x4'])
        self.assertEqual(image.getpixel((0,0)),(255,0,0))
        self.assertEqual(image.getpixel((1199,1599)),(0,0,255))

    def test_missing_wide_cover_or_changed_title_is_not_current(self):
        build_all(self.project)
        self.assertTrue(check_title_outputs(self.project))
        path=self.project/'最终成片/封面_16x9.jpg';previous=path.read_bytes();path.unlink()
        self.assertFalse(check_title_outputs(self.project))
        path.write_bytes(previous)
        write_json(self.project/'00_项目配置.json',{'title':'改了标题'})
        self.assertFalse(check_title_outputs(self.project))

    def test_prepare_emits_three_independent_generation_jobs(self):
        plan=read_json(prepare(self.project))
        self.assertEqual(len(plan['jobs']),3)
        self.assertEqual(len({row['output'] for row in plan['jobs']}),3)
        self.assertEqual(plan['title_region'],list(TITLE_REGION))
        for job in plan['jobs']:
            self.assertIn(job['ratio'].replace('x', ':'), job['prompt'])
            if job['ratio']=='3x4': self.assertNotIn('16:9', job['prompt'])

    def test_adding_third_cover_preserves_bound_two_cover_video_review(self):
        build_all(self.project)
        source=self.project/'work/remix.mp4';source.write_bytes(b'synthetic')
        write_json(self.project/'work/recipe.json',{})
        (self.project/'work/captions.srt').write_text('fixture')
        path=delivery.prepare_review(self.project,source);review=read_json(path)
        review.update(opening_complete=True,body_ok=True,covers_ok=True,audio_mode='machine_only')
        review['binding']['config']=sha256(self.project/'00_项目配置.json')
        review['binding'].pop('config_file_sha256')
        review['binding']['covers'].pop('16x9')
        review['binding'].pop('cover_layout')
        write_json(path,review)
        delivery.prepare_review(self.project,source)
        refreshed=read_json(path)
        self.assertTrue(refreshed['body_ok']);self.assertTrue(refreshed['opening_complete'])
        self.assertFalse(refreshed['covers_ok'])

    def test_cover_only_layout_edit_preserves_video_observations(self):
        build_all(self.project)
        source=self.project/'work/remix.mp4';source.write_bytes(b'synthetic fixture, not real video')
        write_json(self.project/'work/recipe.json',{})
        (self.project/'work/captions.srt').write_text('fixture')
        path=delivery.prepare_review(self.project,source)
        review=read_json(path);review.update(opening_complete=True,body_ok=True,covers_ok=True,audio_mode='machine_only')
        write_json(path,review)
        cfg=read_json(self.project/'00_项目配置.json');cfg['covers']={'title_lines':{'3x4':[self.title[:12],self.title[12:]]}}
        write_json(self.project/'00_项目配置.json',cfg)
        build_all(self.project)
        delivery.prepare_review(self.project,source)
        result=read_json(path)
        self.assertTrue(result['opening_complete']);self.assertTrue(result['body_ok'])
        self.assertEqual(result['audio_mode'],'machine_only');self.assertFalse(result['covers_ok'])


if __name__=='__main__':unittest.main()
