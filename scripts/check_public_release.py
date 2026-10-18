"""Check the public checkout for excluded content and likely accidental secrets."""
from __future__ import annotations
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEXT_EXTENSIONS = {'.py', '.ps1', '.md', '.json', '.js', '.ts', '.tsx', '.txt', '.yaml', '.yml'}
SKIP = {'.git', '.venv', 'node_modules', '__pycache__', '.pytest_cache'}
PRIVATE_TERMS = ['voice' + 'box', 'qw' + 'en', 'chatter' + 'box',
                 'voice_' + 'split_plan', 'process_' + 'voiceover', 'audit_' + 'voice_stumble',
                 '稳定' + '单样本', 'profile_' + 'name']
SECRET_PATTERNS = [r'gh[pousr]_[A-Za-z0-9]{30,}', r'github_pat_[A-Za-z0-9_]{40,}',
                   r'sk-[A-Za-z0-9_-]{32,}', r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----']


def check(root=ROOT):
    findings = []
    files = 0
    for path in root.rglob('*'):
        rel = path.relative_to(root)
        if set(rel.parts) & SKIP or not path.is_file():
            continue
        files += 1
        if path.suffix not in TEXT_EXTENSIONS and path.name not in {'LICENSE', '.gitignore', '.gitattributes'}:
            findings.append({'file': rel.as_posix(), 'reason': 'unexpected_nontext_file'})
            continue
        text = path.read_text(encoding='utf-8-sig')
        for term in PRIVATE_TERMS:
            if term.casefold() in text.casefold() or term.casefold() in rel.as_posix().casefold():
                findings.append({'file': rel.as_posix(), 'reason': 'excluded_private_implementation'})
                break
        if re.search(r'(?i)[A-Z]:[/\\](?:Users[/\\]|Python[/\\]|Voice|Agent|life-experience)', text):
            findings.append({'file': rel.as_posix(), 'reason': 'developer_machine_path'})
        if any(re.search(pattern, text) for pattern in SECRET_PATTERNS):
            findings.append({'file': rel.as_posix(), 'reason': 'possible_secret'})
        if path.suffix == '.md':
            for target in re.findall(r'\]\(([^)]+)\)', text):
                if '://' in target or target.startswith(('#', '<')):
                    continue
                local = target.split('#')[0]
                if local and not (path.parent / local).is_file():
                    findings.append({'file': rel.as_posix(), 'reason': 'missing_document_link', 'target': local})
    return {'passed': not findings, 'files_checked': files, 'findings': findings,
            'limitation': 'Local heuristic check; not a rights clearance or exhaustive secret audit.'}


if __name__ == '__main__':
    report = check()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(0 if report['passed'] else 2)
