"""Run at 04:00 KST when the published snapshot is behind the last closed month.

GitHub Actions cron runs in UTC and may be delayed or skipped. A daily cron
with a snapshot guard retries missed/failed monthly updates, while skipping
costly collection after a month has been published. A code push also catches
up a stale snapshot; a manual dispatch always runs, even when up to date.
"""
import datetime as dt
import json
import os
import re
from pathlib import Path
from zoneinfo import ZoneInfo

KST = ZoneInfo('Asia/Seoul')
SNAPSHOT = Path(__file__).resolve().parents[1] / 'data' / 'site-data.json'


def last_closed_month(instant=None):
    today = (instant or dt.datetime.now(dt.timezone.utc)).astimezone(KST).date()
    return (today.replace(day=1) - dt.timedelta(days=1)).strftime('%Y-%m')


def published_month(path=SNAPSHOT):
    """Read only the small manifest; regional data files are not needed."""
    try:
        value = json.loads(Path(path).read_text(encoding='utf-8'))['meta']['current_month']
        if re.fullmatch(r'\d{4}-(?:0[1-9]|1[0-2])', value):
            return value
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return None


def due(event, instant=None, published=None):
    if event == 'workflow_dispatch':
        return True
    if event not in ('schedule', 'push'):
        return False
    # If the manifest cannot be read, run the pipeline so its validation can
    # report the actual issue rather than skipping a needed update.
    published = published if published is not None else published_month()
    return published is None or published < last_closed_month(instant)


if __name__ == '__main__':
    value = str(due(os.getenv('GITHUB_EVENT_NAME', ''))).lower()
    print(f'갱신 필요: {value} (공개 {published_month() or "미확인"} / 마감 {last_closed_month()})')
    if os.getenv('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'], 'a', encoding='utf-8') as out:
            out.write('due=' + value + '\n')
