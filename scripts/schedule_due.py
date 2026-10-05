"""GitHub UTC cron → 한국시간 매월 1일 04시. 수동 실행은 언제나 허용."""
import datetime as dt, os
from zoneinfo import ZoneInfo

def due(event, instant=None):
    if event=='workflow_dispatch':return True
    local=(instant or dt.datetime.now(dt.timezone.utc)).astimezone(ZoneInfo('Asia/Seoul'))
    return event=='schedule' and local.day==1

if __name__=='__main__':
    value=str(due(os.getenv('GITHUB_EVENT_NAME',''))).lower()
    with open(os.environ['GITHUB_OUTPUT'],'a') as f:f.write('due='+value+'\n')
