"""Create a new episode without replacing an existing project."""
import argparse
from pathlib import Path
from validation_cache import read_json, write_json
from visual_style import ROOT

def initialize(project, title):
    if not title.strip(): raise ValueError('A non-empty title is required')
    if project.exists() and any(project.iterdir()): raise ValueError('Project is not empty; resume it instead')
    for folder in ('work', '画面', '配音', '最终成片'): (project / folder).mkdir(parents=True, exist_ok=True)
    intro = read_json(ROOT / 'assets/intro-plan-template.json')['intro']
    intro['topic_lines'] = [[{'text': title, 'color': 'red'}]]
    write_json(project / '00_项目配置.json', {'title': title, 'revision': 1, 'title_mode': 'immersive',
        'style_reference': '',
        'voiceover': {'mode': 'user_supplied', 'processed_audio': '配音/narration.wav'},
        'intro': intro})
    (project / '01_确认文稿.md').write_text('# ' + title + '\n\n', encoding='utf-8')
    (project / '02_配音稿.txt').write_text('', encoding='utf-8')
    return project

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('project',type=Path);p.add_argument('--title',required=True)
    a=p.parse_args();print(initialize(a.project.resolve(),a.title))

if __name__ == '__main__': main()
