"""Check freshness and stage only public website files for explicit deployment."""
import argparse
import json
import os
import shutil
from pathlib import Path
from pipeline import DataError, last_closed_month, read_json, validate_dataset

ROOT = Path(__file__).resolve().parents[1]


def verify_fresh(root=ROOT, target=None):
    target = target or last_closed_month()
    data = read_json(Path(root) / 'data/site-data.json')
    validate_dataset(data)
    actual = data['meta'].get('current_month', '')
    if actual != target:
        raise DataError(f'목표 {target} / 실제 {actual or "미확인"}: 새 월 수집이 완료되지 않았습니다.')
    return actual


def stage_site(root=ROOT, destination=None):
    root = Path(root)
    destination = Path(destination) if destination else root / '_site'
    # Avoid including source code, old snapshots, credentials or test files.
    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True)
    for name in ('index.html', 'assets'):
        source = root / name
        if source.is_dir():
            shutil.copytree(source, destination / name)
        else:
            shutil.copy2(source, destination / name)
    (destination / 'config').mkdir()
    shutil.copy2(root / 'config/supabase.js', destination / 'config/supabase.js')
    manifest = json.loads((root / 'data/site-data.json').read_text())
    # Verify every referenced hash before preparing the artifact.
    data = read_json(root / 'data/site-data.json')
    validate_dataset(data)
    (destination / 'data').mkdir()
    shutil.copy2(root / 'data/site-data.json', destination / 'data/site-data.json')
    for part in manifest.get('_storage', {}).get('parts', []):
        rel = part['file']
        target = destination / 'data' / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(root / 'data' / rel, target)
    (destination / '.nojekyll').touch()
    if (root / 'CNAME').exists():
        shutil.copy2(root / 'CNAME', destination / 'CNAME')
    return destination


def summary(root=ROOT):
    root = Path(root)
    meta = json.loads((root / 'data/site-data.json').read_text())['meta']
    lines = ['## k.APT 업데이트', f'- 목표 월: {last_closed_month()}',
             f'- 실제 수록 월: {meta.get("current_month", "미확인")}',
             f'- 마지막 데이터 갱신: {meta.get("updated_at", "미확인")}',
             '- 실제 사이트 반영은 deploy 작업까지 확인하세요.']
    log = root / 'reports/collection.log'
    if os.getenv('COLLECT_OUTCOME') == 'failure':
        lines += ['- **수집 실패: 이전 정상 데이터를 유지합니다.**',
                  '- collection-report artifact의 collection.log에서 원인을 확인하세요.']
    elif meta.get('current_month', '') < last_closed_month():
        lines += ['- **새 월 미수집: 다음 예약 실행에서 재시도합니다.**']
    report = '\n'.join(lines) + '\n'
    print(report)
    if os.getenv('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as out:
            out.write(report)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['verify', 'stage', 'summary'])
    args = parser.parse_args()
    if args.action == 'verify':
        print('새 월 검증 완료:', verify_fresh())
    elif args.action == 'stage':
        print('배포 파일 준비:', stage_site())
    else:
        summary()
