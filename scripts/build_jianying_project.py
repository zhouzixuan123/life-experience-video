"""Export the current verified timeline. Never regenerate timing or production media."""
import argparse, copy, json, math, shutil, uuid
from pathlib import Path
from validation_cache import read_json, sha256, write_json
ROOT = Path(__file__).resolve().parent.parent

def local(project, value):
    if str(value).startswith('skill://'): return ROOT / str(value)[8:]
    path = Path(str(value))
    return path if path.is_absolute() else project / path

def load_export(project):
    work = project / 'work'
    report = read_json(work / 'delivery_validation.json')
    recipe_path = work / 'recipe.json'
    if report.get('passed') is not True or report.get('recipe_sha256') != sha256(recipe_path):
        raise ValueError('Export needs the current verified recipe; complete normal delivery first')
    recipe = read_json(recipe_path)
    config = read_json(project / '00_项目配置.json')
    if report.get('episode_config_sha256') != sha256(project / '00_项目配置.json'): raise ValueError('Configuration changed since delivery')
    source = local(project, report['source'])
    if report.get('source_sha256') != sha256(source): raise ValueError('Final video changed')
    plan = local(project, recipe['audio_mix']['plan'])
    mix = read_json(plan)
    if recipe['audio_mix'].get('plan_sha256') != sha256(plan): raise ValueError('Mix plan changed since rendering')
    voice = local(project, config['voiceover']['processed_audio'])
    if sha256(voice) != sha256(local(project, mix['voice']['source'])): raise ValueError('Mix and configured voice differ')
    if sha256(voice) not in recipe['audio_mix'].get('source_hashes', {}).values(): raise ValueError('Voice changed since rendering')
    shots = copy.deepcopy(recipe['shots'])
    if not shots: raise ValueError('Current recipe has no shots')
    end = 0.0
    for shot in shots:
        start, stop = float(shot['start_seconds']), float(shot['end_seconds'])
        if not all(map(math.isfinite, (start, stop))) or start < end - .001 or stop <= start:
            raise ValueError('Recipe shot ranges must be explicit, ordered and non-overlapping')
        shot['start_us'] = round(start * 1_000_000)
        shot['duration_us'] = round((stop-start) * 1_000_000)
        end = stop
    return recipe, config, mix, shots, plan

def motion_coordinates(motion):
    result = dict(motion)
    for axis in ('x', 'y'):
        if f'focus_{axis}' not in result: continue
        focus = float(result[f'focus_{axis}'])
        if not math.isfinite(focus) or not 0 <= focus <= 1: raise ValueError('Invalid focus coordinate')
        for endpoint in ('start', 'end'):
            scale = float(result[f'scale_{endpoint}'])
            if not math.isfinite(scale) or scale < 1: raise ValueError('Invalid push scale')
            limit = (scale - 1) / 2
            offset = max(-limit, min(limit, -(focus - .5) * scale))
            result.setdefault(f'{axis}_{endpoint}', offset)
    return result

def export(project):
    import pyJianYingDraft as draft
    recipe, config, mix, shots, plan = load_export(project)
    work = project / 'work'
    target = work / 'jianying_draft'
    pending = work / 'jianying_draft.pending'
    if pending.exists(): raise ValueError('Inspect the existing pending export before retrying')
    pending.mkdir(); (pending / 'assets').mkdir()
    copied = {}
    def asset(value):
        source = local(project, value).resolve()
        if source not in copied:
            dest = pending / 'assets' / (str(len(copied)).zfill(3) + source.suffix)
            shutil.copy2(source, dest);copied[source] = str(dest.resolve())
        return copied[source]
    script = draft.ScriptFile(1920,1080,60,maintrack_adsorb=False)
    script.save_path = str(pending / 'draft_content.json')
    video_track = script.append_track(draft.TrackSpec(draft.TrackType.video, '画面'))
    first = shots[0]['start_us']
    if first:
        # Preserve the actual composited opening as one editable video clip.
        segment = draft.VideoSegment(asset(mix['visual']), draft.trange(0,first), volume=0.0)
        script.add_segment(segment, video_track)
    for shot in shots:
        segment = draft.VideoSegment(asset(shot['image_path']), draft.trange(shot['start_us'],shot['duration_us']), volume=0.0)
        motion = motion_coordinates(shot.get('motion', {}))
        for prop, a, b in [('uniform_scale','scale_start','scale_end'), ('position_x','x_start','x_end'),('position_y','y_start','y_end')]:
            if a in motion and b in motion:
                segment.add_keyframe(getattr(draft.KeyframeProperty,prop),0,float(motion[a]))
                segment.add_keyframe(getattr(draft.KeyframeProperty,prop),shot['duration_us'],float(motion[b]))
        transition = float(recipe.get('transition', {}).get('duration_seconds',0))
        if transition and shot is not shots[-1]: segment.add_transition(draft.TransitionType.叠化,duration=round(transition*1_000_000))
        script.add_segment(segment,video_track)
    duration = round(float(recipe['duration_seconds'])*1_000_000)
    voice_track = script.append_track(draft.TrackSpec(draft.TrackType.audio,'配音'))
    script.add_segment(draft.AudioSegment(asset(config['voiceover']['processed_audio']),draft.trange(0,duration),volume=float(mix['voice'].get('volume',1))),voice_track)
    for group, entries in [('音乐',mix.get('music',{}).get('segments',[])),('音效',mix.get('sound_effects',[]))]:
        # One lane per source segment also preserves explicitly requested overlaps.
        for index,item in enumerate(entries):
            track=script.append_track(draft.TrackSpec(draft.TrackType.audio,f'{group}{index+1}'))
            start=round(float(item['timeline_start'])*1_000_000);length=round(float(item['duration'])*1_000_000)
            segment=draft.AudioSegment(asset(item['source']),draft.trange(start,length),
                source_timerange=draft.trange(round(float(item.get('source_start',0))*1_000_000),length),volume=float(item.get('volume',1)))
            segment.add_fade(round(float(item.get('fade_in',0))*1_000_000),round(float(item.get('fade_out',0))*1_000_000))
            script.add_segment(segment,track)
    captions=asset('work/captions.srt')
    script.import_srt(captions,'字幕',text_style=draft.TextStyle(size=5.8,bold=True,auto_wrapping=False),clip_settings=draft.ClipSettings(transform_y=-.78))
    script.save()
    identity=str(uuid.uuid4())
    content=read_json(pending/'draft_content.json');content['id']=identity;write_json(pending/'draft_content.json',content)
    meta=json.loads(Path(draft.assets.get_asset_path('DRAFT_META_TEMPLATE')).read_text(encoding='utf-8'))
    meta.update(draft_id=identity,draft_name=config['title'],draft_fold_path=str(target.resolve()),draft_root_path=str(target.resolve()),tm_duration=duration)
    write_json(pending/'draft_meta_info.json',meta)
    write_json(pending/'draft_root_index.json',{'id':identity,'root_index_id':identity,'draft_path':str(target.resolve())})
    write_json(pending/'recipe.json',recipe)
    write_json(pending/'export_manifest.json',{'exporter':'current-timeline-v1','recipe_sha256':sha256(work/'recipe.json'),
               'mix_plan_sha256':sha256(plan),'note':'Opening is one composited clip; body images, keyframes, captions and sound tracks remain editable.'})
    # Rebind copied paths before installing. Only exporter-owned rollback data is replaced.
    for path in pending.glob('*.json'):
        path.write_text(path.read_text(encoding='utf-8').replace(str(pending.resolve()).replace('\\','\\\\'),str(target.resolve()).replace('\\','\\\\')),encoding='utf-8')
    backup=work/'archive/rollback/jianying_draft'
    if target.exists():
        if backup.exists():
            if backup.resolve().parent != (work/'archive/rollback').resolve() or read_json(backup/'export_manifest.json').get('exporter')!='current-timeline-v1':
                raise ValueError('Unrecognized rollback directory; preserve it')
            shutil.rmtree(backup)
        backup.parent.mkdir(parents=True,exist_ok=True)
        if target.resolve().parent != work.resolve(): raise ValueError('Unexpected export target')
        target.replace(backup)
    pending.replace(target)
    return target

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('project_dir',type=Path)
    a=p.parse_args();print(export(a.project_dir.resolve()))

if __name__ == '__main__': main()
