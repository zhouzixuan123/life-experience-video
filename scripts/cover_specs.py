"""Shared cover dimensions and the centered title reservation."""
from validation_cache import read_json, sha256

COVER_SIZES = {'4x3': (1600, 1200), '3x4': (1200, 1600), '16x9': (1920, 1080)}
TITLE_REGION = (.08, .32, .92, .68)


def output_path(project, ratio):
    return project / '最终成片' / f'封面_{ratio}.jpg'


def check_title_outputs(project):
    """Cheap reuse of typography's actual output hashes, not another visual audit."""
    report_path = project / 'work/cover_layout_validation.json'
    if not report_path.is_file():
        return False
    report = read_json(report_path)
    title = str(read_json(project / '00_项目配置.json').get('title', '')).strip()
    records = report.get('covers', [])
    if (report.get('schema_version') != 2 or report.get('title') != title or not title
            or len(records) != len(COVER_SIZES)
            or {row.get('ratio') for row in records} != set(COVER_SIZES)):
        return False
    for row in records:
        path = output_path(project, row['ratio'])
        if (row.get('passed') is not True or ''.join(row.get('title_lines', [])) != title
                or row.get('size') != list(COVER_SIZES[row['ratio']])
                or not path.is_file() or row.get('sha256') != sha256(path)):
            return False
    return True
