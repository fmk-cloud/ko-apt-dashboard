"""Bounded cache for public query responses; failed/partial responses are not saved."""
import datetime as dt
import hashlib
import json
from pipeline import atomic_json, now

MAX_AGE_SECONDS = 48 * 3600

def rows_hash(rows):
    return hashlib.sha256(json.dumps(rows,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()

def load_response(path,query,instant=None):
    try:
        data=json.loads(path.read_text())
        stamp=dt.datetime.fromisoformat(data['checked_at'])
        age=((instant or dt.datetime.now(dt.timezone.utc))-stamp).total_seconds()
        if data['version']!=1 or data['query']!=query or not 0<=age<=MAX_AGE_SECONDS:return None
        if not isinstance(data['rows'],list) or data['rows_hash']!=rows_hash(data['rows']):return None
        if not isinstance(data['sha256'],str) or len(data['sha256'])!=64:return None
        return data
    except (OSError,ValueError,KeyError,TypeError):return None

def save_response(path,query,rows,source_hash,checked_at=None):
    atomic_json(path,{'version':1,'query':query,'rows':rows,'rows_hash':rows_hash(rows),'sha256':source_hash,'checked_at':checked_at or now()})
