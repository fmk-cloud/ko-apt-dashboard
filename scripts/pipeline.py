"""서울·경기 공식 공개자료 수집 공통 검증. Python 3.11+, 표준 라이브러리만 사용."""
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
    for attempt in range(attempts):
        try:
            req=urllib.request.Request(url,data=data,headers={'User-Agent':'k-APT-Seoul/26'})
            with urllib.request.urlopen(req,timeout=35) as r: return r.read()
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

def region_maps(settings):
    regions=settings.get('regions') or []
    if not regions and settings.get('region_code') and settings.get('region'):
        regions=[{'code':settings['region_code'],'name':settings['region'],'minimum_expected_complexes':1}]
    if not regions: raise DataError('수집 자치구 설정 없음')
    by_name={r['name']:str(r['code']) for r in regions}
    by_code={str(r['code']):r['name'] for r in regions}
    if len(by_name)!=len(regions) or len(by_code)!=len(regions): raise DataError('자치구 설정 중복')
    return regions,by_name,by_code


def parse_metadata_jibun(detail):
    s=unicodedata.normalize('NFKC',str(detail or '')).strip()
    # OA-15818 DADDR는 지번 또는 단지명 등 혼합 필드이므로 숫자가 명확한 경우에만 사용한다.
    m=re.search(r'(?<!\d)(\d{1,4}(?:-\d{1,4})?)\s*번지(?:\s|$)',s)
    if m: return m.group(1)
    if re.fullmatch(r'\d{1,4}(?:-\d{1,4})?',s): return s
    m=re.search(r'[가-힣]+동\s*(\d{1,4}(?:-\d{1,4})?)$',s)
    return m.group(1) if m else ''


def parse_standard_address_jibun(address, region, legal_dong):
    """OA-15818 APT_STDG_ADDR에서 '구 + 법정동 + 지번'이 명시된 경우만 지번을 추출한다.
    공식 페이지가 이 필드의 정확도 한계를 안내하므로 지역·법정동이 모두 일치하지 않으면 사용하지 않는다.
    """
    s=unicodedata.normalize('NFKC',str(address or '')).strip()
    if not s or not region or not legal_dong or region not in s or legal_dong not in s: return ''
    tail=s.split(legal_dong,1)[1].strip()
    m=re.match(r'^(?:산\s*)?(\d{1,4}(?:-\d{1,4})?)(?:\s|번지|$)',tail)
    return m.group(1) if m else ''


def master_parcel_evidence(row, region, legal_dong):
    daddr=parse_metadata_jibun(pick(row,'DADDR'))
    stdg=parse_standard_address_jibun(pick(row,'APT_STDG_ADDR','KAPT_ADDR'),region,legal_dong)
    if daddr and stdg and daddr!=stdg:
        return '', 'conflict'
    if daddr and stdg: return daddr,'daddr+stdg_addr'
    if daddr: return daddr,'daddr'
    # APT_STDG_ADDR 단독은 공식 페이지의 정확도 주의 문구 때문에 자동연결 근거로 사용하지 않는다.
    if stdg: return '', 'stdg_addr_only_untrusted'
    return '', 'none'


def normalize_master(rows, previous, settings=None):
    settings=settings or {'regions':[{'code':'11560','name':'영등포구','minimum_expected_complexes':50}],'minimum_households':300}
    regions,by_name,_=region_maps(settings); allowed=set(by_name)
    minimum_households=int(settings.get('minimum_households',300))
    old={c['id']:c for c in previous}; result=[]; seen=set(); unknown=[]
    per_region={r['name']:0 for r in regions}
    for r in rows:
        r={k.upper():v for k,v in r.items()}
        district=pick(r,'SGG_ADDR','SIGUNGU'); address=pick(r,'APT_RDN_ADDR','KAPT_NEWADRS','RDN_ADDR')
        region=district if district in allowed else next((name for name in allowed if name in address), '')
        if not region: continue
        cid=pick(r,'APT_CD','KAPT_CODE'); name=pick(r,'APT_NM','KAPT_NAME')
        if not cid or not name: raise DataError(f'{region} 단지 코드/명 누락: 메타데이터 필드 변경 확인')
        if cid in seen: raise DataError('메타데이터 단지 코드 중복')
        seen.add(cid)
        hh=pick(r,'TNOHSH','KAPTD_PCNT')
        try: hh=int(float(hh.replace(',','')))
        except ValueError:
            unknown.append({'id':cid,'name':name,'region':region,'reason':'세대수 미확인'}); continue
        if hh<minimum_households: continue
        kind=pick(r,'CMPX_CLSF','CODE_APT_NM')
        tenure=pick(r,'HH_TYPE','CODE_SALE_NM')
        if kind and '아파트' not in kind and '주상복합' not in kind: continue
        if tenure and '임대' in tenure and '분양' not in tenure and '혼합' not in tenure: continue
        c=copy.deepcopy(old.get(cid,{}))
        raw_date=pick(r,'USE_APRV_YMD','KAPT_USEDATE')
        if raw_date.isdigit() and len(raw_date)>=11:
            completed=dt.datetime.fromtimestamp(int(raw_date)/1000,KST).strftime('%Y%m%d')
        else: completed=re.sub(r'[^0-9]','',raw_date)
        detail=pick(r,'DADDR')
        legal_dong=pick(r,'EMD_ADDR','DONG')
        metadata_jibun,jibun_evidence=master_parcel_evidence(r,region,legal_dong)
        c.update(id=cid,region=region,name=c.get('name') or name,address=address or c.get('address',''),households=hh,
                 legal_dong=legal_dong,official_name=name,metadata_detail_address=detail,
                 metadata_jibun=metadata_jibun,metadata_jibun_evidence=jibun_evidence,
                 metadata_source=MASTER_SOURCE,metadata_checked_at=now())
        c['aliases']=sorted(set(c.get('aliases',[])+[name,c['name']]))
        if len(completed)>=6: c.update(completed=completed[:4]+'.'+completed[4:6],build_year=int(completed[:4]))
        c['metadata_type']=kind;c['tenure']=tenure
        c.setdefault('completed',''); c.setdefault('far',None); c.setdefault('station',''); c.setdefault('station_display','')
        c.setdefault('naver','https://new.land.naver.com/search?sk='+urllib.parse.quote(c['name']))
        c.pop('tx',None); result.append(c); per_region[region]+=1
    if unknown: raise DataError(f'{len(unknown)}개 단지 세대수 미확인: 목록을 축소하지 않고 중단')
    prev_counts={name:sum(1 for c in previous if c.get('region')==name) for name in allowed}
    for spec in regions:
        name=spec['name']; count=per_region[name]; old_count=prev_counts.get(name,0)
        floor=int(spec.get('minimum_expected_complexes',1))
        if old_count:
            floor=max(floor,int(old_count*.8))
        if count<floor: raise DataError(f'{name} 기준 단지 목록 급감({count}개 < {floor}개): 기존 목록 유지')
    total_floor=int(settings.get('minimum_expected_total_complexes',0) or 0)
    if total_floor and len(result)<total_floor:
        raise DataError(f'서울 전체 기준 단지 목록 급감({len(result)}개 < {total_floor}개): 기존 목록 유지')
    return sorted(result,key=lambda c:(c['region'],c['id']))

def validate_dataset(d, settings=None):
    cs=d.get('complexes',[])
    if not cs: raise DataError('단지 목록 없음')
    if settings is None:
        allowed=set(d.get('meta',{}).get('loaded_regions') or ['영등포구']); minimum_households=300
    else:
        regions,_,_=region_maps(settings); allowed={r['name'] for r in regions}; minimum_households=int(settings.get('minimum_households',300))
    ids=set()
    for c in cs:
        if c['id'] in ids: raise DataError('단지 ID 중복')
        ids.add(c['id'])
        if c.get('region') not in allowed or not isinstance(c.get('households'),int) or c['households']<minimum_households: raise DataError('수집 범위 위반')
        for t in c.get('tx',[]):
            try: dt.date.fromisoformat(t[0])
            except (ValueError,TypeError): raise DataError('거래 날짜 오류') from None
            if len(t)<4 or not all(isinstance(v,(int,float)) and math.isfinite(v) for v in t[1:4]) or t[1]<=0 or t[3]<=0: raise DataError('거래 수치 오류')
    return True
