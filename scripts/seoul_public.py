"""공식 서울시 공개 내려받기. 인증키 없이 제공되는 JSON export를 사용한다.
스크래핑한 가격/예측값을 만들지 않으며, 응답 실패·범위 급감 시 공개 파일을 유지한다.
"""
import collections,copy,datetime as dt,hashlib,json,os,re,urllib.parse
from pathlib import Path
from pipeline import (DataError,request_bytes,now,read_json,atomic_json,normalize_master,
                      month_range,last_closed_month,validate_dataset,norm)
from embed_data import embedded_html

EXPORT='https://datafile.seoul.go.kr/bigfile/iot/sheet/json/download.do'
MASTER='https://data.seoul.go.kr/dataList/OA-15818/S/1/datasetView.do'
TRADES='https://data.seoul.go.kr/dataList/OA-21275/S/1/datasetView.do'

def download(dataset,fetch=request_bytes):
    params={'srvType':'S','infId':dataset,'serviceKind':'1','pageNo':'1','ssUserId':'SAMPLE_VIEW',
            'strWhere':'','strOrderby':'SN ASC' if dataset=='OA-15818' else '',
            'filterCol':'CGG_CD' if dataset=='OA-21275' else '',
            'txtFilter':'11560' if dataset=='OA-21275' else ''}
    blob=fetch(EXPORT,urllib.parse.urlencode(params).encode())
    try:obj=json.loads(blob)
    except (ValueError,UnicodeDecodeError):raise DataError('서울시 공개 내려받기 JSON 오류: 기존 데이터 유지') from None
    if not isinstance(obj,dict) or not isinstance(obj.get('DATA'),list) or not obj['DATA']:raise DataError('서울시 내려받기 DATA 목록 없음')
    return obj['DATA'],hashlib.sha256(blob).hexdigest()

def lower(row):return {k.lower():v for k,v in row.items()}
def clean(v):return '' if v is None else str(v).strip()
def parcel(r):
    try:
        a=int(r['mno']);b=int(r.get('sno') or 0)
        return str(a)+('-'+str(b) if b else '')
    except (KeyError,ValueError,TypeError):raise DataError('거래 지번 필드 오류') from None

def binding_key(r):return (clean(r.get('stdg_nm')),parcel(r),norm(clean(r.get('bldg_nm'))),int(r.get('arch_yr') or 0))
def load_bindings(rows,catalog):
    cat={c['id']:c for c in catalog};result={}
    for r in rows:
        if r['complex_id'] not in cat:continue  # retired/rental/small complex removed from the current catalog
        c=cat[r['complex_id']]
        if c.get('legal_dong')!=r['legal_dong'] or abs(c.get('build_year',0)-r['build_year'])>2:raise DataError('단지 연결표와 최신 단지정보 충돌: '+c['name'])
        k=(r['legal_dong'],r['jibun'],norm(r['trade_name']),r['build_year'])
        if k in result and result[k]!=r['complex_id']:raise DataError('지번·단지명 연결표 중복')
        result[k]=r['complex_id']
    return result

def collect(catalog,raw,bindings,old,start,end):
    rows=[lower(r) for r in raw]
    if len(rows)<100:raise DataError('서울시 영등포구 전체 응답이 100건 미만: 불완전 다운로드 의심')
    if any(clean(r.get('cgg_cd'))!='11560' for r in rows):raise DataError('영등포구 외 자료 또는 자치구 필드 변경: 중단')
    receipt_years=sorted({int(r['rcpt_yr']) for r in rows if clean(r.get('rcpt_yr')).isdigit()})
    if not receipt_years:raise DataError('접수연도 필드 없음')
    # Export retains a rolling receipt-year window. Avoid treating late prior-year filings as a complete older year.
    fresh_start=f'{receipt_years[0]}-01';effective_start=max(start,fresh_start)
    if effective_start>end:raise DataError('제공되는 데이터와 요청 기간이 겹치지 않음')
    months=month_range(effective_start,end)
    by_id={c['id']:dict(copy.deepcopy(c),tx=[]) for c in catalog}
    old_by_id={c['id']:c for c in old.get('complexes',[])}
    preserve_older=old.get('meta',{}).get('source_verified') and old.get('meta',{}).get('provider')=='seoul_public'
    if preserve_older:
        for cid,c in by_id.items():c['tx']=[t for t in old_by_id.get(cid,{}).get('tx',[]) if start<=t[0][:7]<effective_start]
    index=load_bindings(bindings,catalog);stats=collections.Counter();counts=collections.Counter();unmapped=collections.Counter();connected=set();names={}
    for r in rows:
        if clean(r.get('bldg_usg'))!='아파트':stats['non_apartment']+=1;continue
        if clean(r.get('rght_se')) not in ('','소유권'):stats['rights_excluded']+=1;continue
        date=clean(r.get('ctrt_day'))
        try:
            date=dt.date(int(date[:4]),int(date[4:6]),int(date[6:8])).isoformat()
        except (ValueError,TypeError):raise DataError('계약일 형식 오류') from None
        if not effective_start<=date[:7]<=end:continue
        counts[date[:7]]+=1
        try:k=binding_key(r)
        except (ValueError,TypeError):raise DataError('건축년도 필드 오류') from None
        cid=index.get(k)
        if not cid:
            # Strict automatic path for newly added complexes: exact name + dong + year, unique candidate.
            candidates=[c for c in catalog if c.get('legal_dong')==k[0] and c.get('build_year')==k[3]
                        and k[2] in {norm(c['name']),norm(c.get('official_name',''))}]
            if len(candidates)==1:
                candidate=candidates[0]
                known={bk[1] for bk,cv in index.items() if cv==candidate['id']}
                if not known or k[1] in known:
                    cid=candidate['id'];index[k]=cid;stats['new_exact_binding']+=1
            if not cid:
                unmapped[(k[0],k[1],clean(r.get('bldg_nm')),k[3])]+=1;continue
        connected.add(cid)
        if clean(r.get('rtrcn_day')) not in ('','-','0'):stats['cancelled']+=1;continue
        try:
            price=int(clean(r['thing_amt']).replace(',',''));area=float(r['arch_area']);floor=int(r['flr'])
        except (ValueError,KeyError,TypeError):raise DataError('연결 거래 수치 필드 오류') from None
        if price<=0 or not 0<area<2000 or not -10<=floor<=200:raise DataError('연결 거래 수치 범위 오류')
        by_id[cid]['tx'].append([date,area,floor,price,k[0],'',k[1]])
        stats['saved']+=1
    if any(not counts[m] for m in months):raise DataError('아파트 원자료가 통째로 없는 월이 있습니다: 기존 데이터 유지')
    for cid,c in by_id.items():
        c['tx'].sort(key=lambda t:(t[0],t[1],t[2],t[3]))
        c['data_status']='collected' if c['tx'] else ('no_active_trades' if cid in connected else 'matching_unconfirmed')
        c['trade_source']='서울시 공개 실거래(국토교통부 연계)'
        c['coverage_from']=start if preserve_older else effective_start;c['coverage_to']=end
    meta={'status':'live','provider':'seoul_public','source_verified':True,'updated_at':now(),
          'current_month':end,'min_month':start if preserve_older else effective_start,
          'loaded_regions':['영등포구'],'complex_count':len(by_id),'minimum_households':300,
          'metadata_status':'refreshed','refreshed_from':effective_start,'metadata_checked_at':now(),
          'older_history_frozen':bool(preserve_older and start<effective_start),
          'schedule':'매월 1일 04:00 Asia/Seoul',
          'sources':{'trades':TRADES,'metadata':MASTER},
          'note':'매월 공식 공개자료 재수집. 취소 거래/분양권/입주권/임대전용/300세대 미만 제외. 용적률·전세 갭 미지원.'}
    d={'meta':meta,'complexes':list(by_id.values())};validate_dataset(d)
    if stats['saved']==0:raise DataError('대상 거래 연결 0건')
    # Protect each existing, live complex against silent loss, including a changed name or parcel.
    for cid,c in by_id.items():
        before=sum(effective_start<=t[0][:7]<=end for t in old_by_id.get(cid,{}).get('tx',[]))
        after=sum(effective_start<=t[0][:7]<=end for t in c['tx'])
        if preserve_older and before>=10 and after<before*.5:raise DataError('단지 거래 급감: '+c['name']+' — 연결/취소 자료 확인 필요')
    unresolved=[{'id':c['id'],'name':c['name'],'reason':'연결 가능한 거래 없음(거래 없음·재건축·이름 변경 여부 확인 필요)'} for c in by_id.values() if c['data_status']=='matching_unconfirmed']
    report={'status':'success','published':True,'finished_at':now(),'complex_count':len(by_id),'trade_count':sum(len(c['tx']) for c in by_id.values()),
            'stats':dict(stats),'raw_month_counts':dict(sorted(counts.items())),'receipt_years':receipt_years,
            'unresolved_complexes':unresolved,'excluded_or_unmatched_buildings':[{'dong':k[0],'jibun':k[1],'name':k[2],'year':k[3],'count':v} for k,v in sorted(unmapped.items())],
            'notice':'제외/미연결 목록에는 300세대 미만과 대상 외 단지도 포함됩니다. 이 목록의 거래 상세는 저장하지 않습니다.'}
    return d,report

def run_public(root,fetch=request_bytes,master_rows=None,trade_rows=None):
    root=Path(root);old=read_json(root/'data/site-data.json');previous=read_json(root/'data/complexes.json')
    try:
        hashes={}
        if master_rows is None:master_rows,hashes['metadata']=download('OA-15818',fetch)
        catalog=normalize_master(master_rows,previous)
        exclusions=read_json(root/'config/catalog-exclusions.json')
        blocked={x['id'] for x in exclusions}
        catalog=[c for c in catalog if c['id'] not in blocked]
        if trade_rows is None:trade_rows,hashes['trades']=download('OA-21275',fetch)
        settings=read_json(root/'config/settings.json');end=last_closed_month()
        d,report=collect(catalog,trade_rows,read_json(root/'config/seoul-bindings.json'),old,settings['start_month'],end)
        report['source_sha256']=hashes
        report['catalog_exclusions']=exclusions
        d['meta']['catalog_exclusions']=exclusions
        html=embedded_html((root/'index.html').read_text(encoding='utf-8'),d)
        atomic_json(root/'data/site-data.previous.json',old)
        atomic_json(root/'data/site-data.json',d)
        atomic_json(root/'data/complexes.json',catalog)
        temp=root/'index.html.tmp';temp.write_text(html,encoding='utf-8');os.replace(temp,root/'index.html')
        atomic_json(root/'reports/update-report.json',report)
        print(f"서울시 공식 자료 수집 완료: {report['complex_count']}개 단지 / {report['trade_count']}건 / 미연결 {len(report['unresolved_complexes'])}개",flush=True)
        return report
    except (DataError,ValueError,KeyError,TypeError) as e:
        # No key, URL with credentials, or response payload is printed.
        msg=str(e) if isinstance(e,DataError) else '응답 형식 또는 파일 검증 오류: 기존 데이터 유지'
        atomic_json(root/'reports/update-report.json',{'status':'failed','published':False,'finished_at':now(),'error':msg})
        raise DataError(msg) from None
