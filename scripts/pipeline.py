"""서울시 공개자료 수집 공통 검증. Python 3.11+, 표준 라이브러리만 사용."""
import copy, datetime as dt, json, math, os, re, time, unicodedata
import urllib.error, urllib.parse, urllib.request
from pathlib import Path
from zoneinfo import ZoneInfo
KST=ZoneInfo('Asia/Seoul')
MASTER_SOURCE='https://data.seoul.go.kr/dataList/OA-15818/S/1/datasetView.do'

class DataError(Exception): pass

def now(): return dt.datetime.now(KST).isoformat(timespec='seconds')

def read_json(p): return json.loads(Path(p).read_text(encoding='utf-8'))

def atomic_json(p, obj):
    p=Path(p); p.parent.mkdir(parents=True,exist_ok=True)
    tmp=p.with_suffix(p.suffix+'.tmp')
    tmp.write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    os.replace(tmp,p)

def month_range(start,end):
    try:
        a=dt.date.fromisoformat(start+'-01'); b=dt.date.fromisoformat(end+'-01')
    except ValueError: raise DataError('월 형식은 YYYY-MM입니다.') from None
    if a>b: raise DataError('시작월이 종료월보다 늦습니다.')
    out=[]
    while a<=b:
        out.append(a.strftime('%Y-%m')); a=dt.date(a.year+(a.month==12),a.month%12+1,1)
    return out

def last_closed_month():
    d=dt.datetime.now(KST).date().replace(day=1)-dt.timedelta(days=1)
    return d.strftime('%Y-%m')

def request_bytes(url, data=None, attempts=3):
    # Do not include exception URLs/messages: those can contain service keys.
    for attempt in range(attempts):
        try:
            req=urllib.request.Request(url,data=data,headers={'User-Agent':'k-APT-YDP/20','Referer':'https://data.seoul.go.kr/'})
            with urllib.request.urlopen(req,timeout=90) as r: return r.read()
        except urllib.error.HTTPError as e:
            if e.code not in (408,429,500,502,503,504): raise DataError(f'HTTP {e.code}: 인증·이용승인·접속 상태 확인') from None
            reason=f'HTTP {e.code}'
        except (urllib.error.URLError,TimeoutError,OSError): reason='네트워크 연결/시간초과'
        if attempt+1<attempts: time.sleep(2**attempt)
    raise DataError(reason+' (3회 시도 실패)')

def pick(row,*keys):
    for k in keys:
        v=row.get(k)
        if v is not None and str(v).strip(): return str(v).strip()
    return ''

def norm(s):
    return re.sub(r'[^0-9a-z가-힣]','',unicodedata.normalize('NFKC',str(s)).lower().replace('아파트',''))

def normalize_master(rows, previous):
    old={c['id']:c for c in previous}; result=[]; seen=set(); unknown=[]
    for r in rows:
        r={k.upper():v for k,v in r.items()}
        district=pick(r,'SGG_ADDR','SIGUNGU','SIGUNGU'); address=pick(r,'APT_RDN_ADDR','KAPT_NEWADRS','kaptAddr','RDN_ADDR')
        if district!='영등포구' and '영등포구' not in address: continue
        cid=pick(r,'APT_CD','KAPT_CODE','kaptCode'); name=pick(r,'APT_NM','KAPT_NAME','kaptName')
        if not cid or not name: raise DataError('영등포구 단지 코드/명 누락: 메타데이터 필드 변경 확인')
        if cid in seen: raise DataError('메타데이터 단지 코드 중복')
        seen.add(cid)
        hh=pick(r,'TNOHSH','KAPTD_PCNT','kaptdaCnt')
        try: hh=int(float(hh.replace(',','')))
        except ValueError:
            unknown.append({'id':cid,'name':name,'reason':'세대수 미확인'}); continue
        if hh<300: continue
        kind=pick(r,'CMPX_CLSF','CODE_APT_NM','codeAptNm')
        tenure=pick(r,'HH_TYPE','CODE_SALE_NM','codeSaleNm')
        if kind and '아파트' not in kind and '주상복합' not in kind: continue
        if tenure and '임대' in tenure and '분양' not in tenure and '혼합' not in tenure: continue
        c=copy.deepcopy(old.get(cid,{}))
        raw_date=pick(r,'USE_APRV_YMD','KAPT_USEDATE','KAPTUSEDATE')
        if raw_date.isdigit() and len(raw_date)>=11:
            completed=dt.datetime.fromtimestamp(int(raw_date)/1000,KST).strftime('%Y%m%d')
        else: completed=re.sub(r'[^0-9]','',raw_date)
        c.update(id=cid,region='영등포구',name=c.get('name') or name,address=address or c.get('address',''),households=hh,
                 legal_dong=pick(r,'EMD_ADDR','DONG','dong'),official_name=name,metadata_source=MASTER_SOURCE,metadata_checked_at=now())
        c['aliases']=sorted(set(c.get('aliases',[])+[name,c['name']]))
        if len(completed)>=6: c.update(completed=completed[:4]+'.'+completed[4:6],build_year=int(completed[:4]))
        c['metadata_type']=kind;c['tenure']=tenure
        c.setdefault('completed',''); c.setdefault('far',None); c.setdefault('station',''); c.setdefault('station_display','')
        c.setdefault('naver','https://new.land.naver.com/search?sk='+urllib.parse.quote(c['name']))
        c.pop('tx',None);c.pop('jeonse_tx',None);result.append(c)
    if unknown: raise DataError(f'영등포구 {len(unknown)}개 단지 세대수 미확인: 목록을 축소하지 않고 중단')
    if len(result)<max(50,int(len(previous)*.8)): raise DataError('영등포구 기준 단지 목록 급감: 기존 목록 유지')
    return sorted(result,key=lambda c:c['id'])

def validate_dataset(d):
    cs=d.get('complexes',[])
    if not cs:raise DataError('단지 목록 없음')
    ids=set()
    for c in cs:
        if c['id'] in ids:raise DataError('단지 ID 중복')
        ids.add(c['id'])
        if c.get('region')!='영등포구' or not isinstance(c.get('households'),int) or c['households']<300:raise DataError('수집 범위 위반')
        for t in c.get('tx',[]):
            try:dt.date.fromisoformat(t[0])
            except (ValueError,TypeError):raise DataError('거래 날짜 오류') from None
            if len(t)<4 or not all(isinstance(v,(int,float)) and math.isfinite(v) for v in t[1:4]) or t[1]<=0 or t[3]<=0:raise DataError('거래 수치 오류')
    return True
