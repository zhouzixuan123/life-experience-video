#!/usr/bin/env python3
"""Three independently composed cover bases; complete titles in the central empty region."""
from __future__ import annotations
import argparse
import re
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
from cover_specs import COVER_SIZES, TITLE_REGION, output_path
from font_utils import resolve_font
from validation_cache import now, read_json, sha256, write_json
from visual_style import resolve as resolve_style

PALETTE = ('#ffdc23', '#ee2823')

def title_from(project):
    config = read_json(project / '00_项目配置.json')
    title = config.get('title')
    if not isinstance(title, str) or not title.strip(): raise ValueError('Project title is missing')
    return title.strip(), config

def base_paths(project):
    return {ratio: project / 'work/covers' / f'base_{ratio}.png' for ratio in COVER_SIZES}

def prepare(project):
    title, _ = title_from(project)
    style = resolve_style(project)
    jobs=[]
    for ratio, size in COVER_SIZES.items():
        aspect=ratio.replace('x', ':')
        orientation='portrait' if ratio=='3x4' else 'landscape'
        cover_style=re.sub(r'(?<![0-9])(?:16\s*[:：]\s*9|4\s*[:：]\s*3|3\s*[:：]\s*4)(?![0-9])',aspect,style['prompt'])
        prompt=(cover_style + f'. Create ONE independently composed {aspect} {orientation} cover, target {size[0]}x{size[1]}. '
                + 'Use the approved character reference for this episode. Topic context only, do not draw these words: ' + title
                + f'. Reserve the central horizontal band from {TITLE_REGION[1]:.0%} to {TITLE_REGION[3]:.0%} of image height and {TITLE_REGION[0]:.0%} to {TITLE_REGION[2]:.0%} of width '
                + 'as calm low-detail negative space for a centered title. It is part of the environment, not a white rectangle. '
                + 'Place the main character and important props outside this band, with a clear margin. '
                + 'Default to a complete head-to-toe character silhouette within the frame, with space around the body; '
                + 'do not cut off the head, torso, hands or feet at the image edge. '
                + 'Recompose specifically for this aspect ratio; do not crop, stretch or reuse another cover as the base. '
                + 'Draw no typography, letters, captions or watermark.')
        jobs.append({'ratio':ratio,'size':list(size),'output':str(base_paths(project)[ratio]),
                     'style_reference':style['reference'],'prompt':prompt})
    path=project/'work/cover_prompts.json'
    write_json(path,{'title':title,'title_region':list(TITLE_REGION),'jobs':jobs,
                     'instructions':'Execute three independent image generations. Attach the same approved style/character references, not another cover. Save each native-ratio base separately.'})
    return path

def cover_resize(path, size):
    with Image.open(path) as source:
        source.load()
        if abs((source.width/source.height)/(size[0]/size[1])-1) > .005:
            raise ValueError(f'{path.name}: wrong aspect ratio. Generate a separate {size[0]}x{size[1]} composition; no cropping is performed.')
        return source.convert('RGB').resize(size, Image.Resampling.LANCZOS)

def wrap_title(title, font, max_width, stroke):
    lines=[];line=''
    for char in title:
        candidate=line+char
        box=font.getbbox(candidate,stroke_width=stroke)
        if line and box[2]-box[0] > max_width:
            lines.append(line);line=char
        else:line=candidate
    if line:lines.append(line)
    return lines

def layout(title, size, manual=None):
    if manual is not None and (not isinstance(manual,list) or not manual or
            not all(isinstance(line,str) and line.strip() for line in manual) or ''.join(manual)!=title):
        raise ValueError('Cover title lines must reproduce the complete project title exactly')
    left,top,right,bottom=[round(v*size[i%2]) for i,v in enumerate(TITLE_REGION)]
    width=right-left-24;height=bottom-top-24
    preferred=round(min(size[0]*.082,size[1]*.105))
    for point in range(preferred,45,-1):
        stroke=max(3,round(point*.06))
        font=ImageFont.truetype(str(resolve_font('bold')),point)
        brand=ImageFont.truetype(str(resolve_font('display')),max(30,round(point*.43)))
        lines=manual or wrap_title(title,font,width,stroke)
        if len(lines)>4:continue
        fonts=[brand]+[font]*len(lines);texts=['人生副本']+lines
        boxes=[f.getbbox(t,stroke_width=stroke) for f,t in zip(fonts,texts)]
        gap=max(8,round(point*.15));total=sum(b[3]-b[1] for b in boxes)+gap*(len(boxes)-1)
        if total>height or any(b[2]-b[0]>width for b in boxes):continue
        y=(size[1]-total)/2
        positions=[]
        for box in boxes:
            x=(size[0]-(box[2]-box[0]))/2
            positions.append({'xy':(x-box[0],y-box[1]),'box':[x,y,x+box[2]-box[0],y+box[3]-box[1]]})
            y+=box[3]-box[1]+gap
        return {'title_lines':lines,'texts':texts,'fonts':fonts,'positions':positions,'stroke':stroke,
                'font_size':point,'region':[left,top,right,bottom]}
    raise ValueError('Complete title does not fit the reserved region. Adjust the cover layout; do not abbreviate the title.')

def build_all(project, bases=None):
    title, config=title_from(project)
    bases=bases or base_paths(project)
    if set(bases)!=set(COVER_SIZES):raise ValueError('All three independently generated bases are required')
    if len({Path(path).resolve() for path in bases.values()})!=3:raise ValueError('Each aspect needs its own base image')
    digests={ratio:sha256(path) for ratio,path in bases.items()}
    if len(set(digests.values()))!=3:raise ValueError('Duplicate base image contents are not independent covers')
    manual=config.get('covers',{}).get('title_lines',{})
    prepared={}
    # Preflight the entire set before writing any output.
    for ratio,size in COVER_SIZES.items():
        prepared[ratio]=(cover_resize(bases[ratio],size),layout(title,size,manual.get(ratio)))
    records=[]
    for ratio,(canvas,info) in prepared.items():
        draw=ImageDraw.Draw(canvas)
        for index,(text,font,pos) in enumerate(zip(info['texts'],info['fonts'],info['positions'])):
            draw.text(pos['xy'],text,font=font,fill='white' if index==0 else PALETTE[(index-1)%2],
                      stroke_width=info['stroke'],stroke_fill='#080808')
        path=output_path(project,ratio);path.parent.mkdir(parents=True,exist_ok=True)
        pending=path.with_name(path.stem+'.pending.jpg');canvas.save(pending,format='JPEG',quality=95)
        if path.is_file() and sha256(path)==sha256(pending): pending.unlink()
        else: pending.replace(path)
        records.append({'ratio':ratio,'title_lines':info['title_lines'],'size':list(canvas.size),
            'base':str(Path(bases[ratio]).resolve()),'base_sha256':digests[ratio],
            'output':str(path.resolve()),'sha256':sha256(path),'font_size':info['font_size'],
            'title_region':info['region'],'boxes':[v['box'] for v in info['positions']], 'passed':True})
    report={'schema_version':2,'title':title,'passed':True,'created_at':now(),'covers':records,
            'limitation':'Confirms source ratios, full title and output pixels. Actual viewing must confirm subjects avoid the reserved region and are complete; file hashes do not prove independent generation history.'}
    write_json(project/'work/cover_layout_validation.json',report)
    return report

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('project_dir',type=Path)
    parser.add_argument('--prepare',action='store_true',help='Write three independent cover prompts; does not call an image service')
    for ratio in COVER_SIZES:parser.add_argument('--base'+ratio,type=Path)
    args=parser.parse_args();project=args.project_dir.resolve()
    if args.prepare:print(prepare(project));return
    defaults=base_paths(project)
    bases={ratio:getattr(args,'base'+ratio) or defaults[ratio] for ratio in COVER_SIZES}
    result=build_all(project,bases)
    print(__import__('json').dumps(result,ensure_ascii=False))

if __name__=='__main__':main()
