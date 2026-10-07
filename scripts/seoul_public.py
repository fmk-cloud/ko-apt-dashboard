"""서울시 공식 공개자료 수집기.
OA-15818 공동주택 메타데이터와 OA-21275 실거래를 사용한다.
기존 정상 자료를 유지하면서 설정된 서울 자치구를 동일 규칙으로 수집하며,
응답 실패·자치구 필터 오류·범위 급감·월 누락·기존 거래 급감 시 정상 스냅샷을 덮어쓰지 않는다.
"""
import collections,copy,datetime as dt,hashlib,json,os,urllib.parse
from pathlib import Path
from pipeline import (DataError,request_bytes,now,read_json,atomic_json,normalize_master,
                      month_range,last_closed_month,validate_dataset,norm,region_maps)
from embed_data import embedded_html
from features_data import enrich

EXPORT='https://datafile.seoul.go.kr/bigfile/iot/sheet/json/download.do'
MASTER='https://data.seoul.go.kr/dataList/OA-15818/S/1/datasetView.do'
TRADES='https://data.seoul.go.kr/dataList/OA-21275/S/1/datasetView.do'

def download(dataset, region_code=None, fetch=request_bytes):
    if dataset=='OA-21275' and not region_code: raise DataError('실거래 자치구 코드 누락')
    params={'srvType':'S','infId':dataset,'serviceKind':'1','pageNo':'1','ssUserId':'SAMPLE_VIEW',
            'strWhere':'','strOrderby':'SN ASC' if dataset=='OA-15818' else '',
            'filterCol':'CGG_CD' if dataset=='OA-21275' else '',
            'txtFilter':str(region_code) if dataset=='OA-21275' else ''}
    blob=fetch(EXPORT,urllib.parse.urlencode(params).encode())
    try: obj=json.loads(blob)
    except (ValueError,UnicodeDecodeError): raise DataError('서울시 공개 내려받기 JSON 오류: 기존 데이터 유지') from None
    if not isinstance(obj,dict) or not isinstance(obj.get('DATA'),list) or not obj['DATA']: raise DataError('서울시 내려받기 DATA 목록 없음')
    return obj['DATA'],hashlib.sha256(blob).hexdigest()

def lower(row): return {k.lower():v for k,v in row.items()}
def clean(v): return '' if v is None else str(v).strip()
def parcel(r):
    try:
        a=int(r['mno']); b=int(r.get('sno') or 0)
        return str(a)+('-'+str(b) if b else '')
    except (KeyError,ValueError,TypeError): raise DataError('거래 지번 필드 오류') from None

def binding_key(r): return (clean(r.get('stdg_nm')),parcel(r),norm(clean(r.get('bldg_nm'))),int(0 if clean(r.get('arch_yr')).lower() in ('','null','none') else r['arch_yr']))

def load_bindings(rows,catalog):
    cat={c['id']:c for c in catalog}; result={}
    for r in rows:
        if r['complex_id'] not in cat: continue
        c=cat[r['complex_id']]
        if c.get('legal_dong')!=r['legal_dong'] or abs(c.get('build_year',0)-r['build_year'])>2: raise DataError('단지 연결표와 최신 단지정보 충돌: '+c['name'])
        k=(c['region'],r['legal_dong'],r['jibun'],norm(r['trade_name']),r['build_year'])
        if k in result and result[k]!=r['complex_id']: raise DataError('지번·단지명 연결표 중복')
        result[k]=r['complex_id']
    return result

def collect(catalog,raw,bindings,old,start,end,settings=None):
    settings=settings or {'regions':[{'code':'11560','name':'영등포구','minimum_expected_complexes':1}],'minimum_households':300}
    regions,_,by_code=region_maps(settings); allowed_codes=set(by_code); loaded_regions=[r['name'] for r in regions]
    rows=[lower(r) for r in raw]
    if len(rows)<100: raise DataError('서울시 대상 자치구 전체 응답이 100건 미만: 불완전 다운로드 의심')
    bad={clean(r.get('cgg_cd')) for r in rows if clean(r.get('cgg_cd')) not in allowed_codes}
    if bad: raise DataError('설정 자치구 외 자료 또는 자치구 필드 변경: 중단')
    receipt_years=sorted({int(r['rcpt_yr']) for r in rows if clean(r.get('rcpt_yr')).isdigit()})
    if not receipt_years: raise DataError('접수연도 필드 없음')
    fresh_start=f'{receipt_years[0]}-01'; effective_start=max(start,fresh_start)
    if effective_start>end: raise DataError('제공되는 데이터와 요청 기간이 겹치지 않음')
    months=month_range(effective_start,end)
    by_id={c['id']:dict(copy.deepcopy(c),tx=[]) for c in catalog}
    old_by_id={c['id']:c for c in old.get('complexes',[])}
    preserve_older=old.get('meta',{}).get('source_verified') and old.get('meta',{}).get('provider') in ('seoul_public','seoul_gyeonggi_official')
    if preserve_older:
        for cid,c in by_id.items(): c['tx']=[t for t in old_by_id.get(cid,{}).get('tx',[]) if start<=t[0][:7]<effective_start]
    index=load_bindings(bindings,catalog)
    stats=collections.Counter(); counts=collections.Counter(); region_counts=collections.Counter(); unmapped=collections.Counter(); connected=set()
    catalog_by_region=collections.defaultdict(list)
    for c in catalog: catalog_by_region[c['region']].append(c)
    for r in rows:
        code=clean(r.get('cgg_cd')); region=by_code[code]
        if clean(r.get('bldg_usg'))!='아파트': stats['non_apartment']+=1; continue
        if clean(r.get('rght_se')) not in ('','소유권'): stats['rights_excluded']+=1; continue
        date=clean(r.get('ctrt_day'))
        try: date=dt.date(int(date[:4]),int(date[4:6]),int(date[6:8])).isoformat()
        except (ValueError,TypeError): raise DataError('계약일 형식 오류') from None
        if not effective_start<=date[:7]<=end: continue
        counts[date[:7]]+=1; region_counts[(region,date[:7])]+=1
        try: k=binding_key(r)
        except (ValueError,TypeError): raise DataError('건축년도 필드 오류') from None
        cid=index.get((region,*k))
        if not cid:
            # 신규 단지는 이름+법정동+건축연도가 모두 정확히 일치하고 후보가 하나뿐일 때만 자동 연결한다.
            candidates=[c for c in catalog_by_region[region] if c.get('legal_dong')==k[0] and c.get('build_year')==k[3]
                        and k[2] in {norm(c['name']),norm(c.get('official_name','')),*{norm(a) for a in c.get('aliases',[])}}]
            if len(candidates)==1:
                candidate=candidates[0]
                known={bk[2] for bk,cv in index.items() if cv==candidate['id']}
                metadata_jibun=clean(candidate.get('metadata_jibun'))
                # 신규 자동 연결은 메타데이터에서 지번까지 명확히 확인된 경우만 허용한다.
                # 지번을 확인할 수 없으면 비슷한 이름이어도 '확인 필요'에 남긴다.
                if (known and k[1] in known) or (metadata_jibun and metadata_jibun==k[1]):
                    cid=candidate['id']; index[(region,*k)]=cid; stats['new_exact_binding']+=1
            if not cid:
                unmapped[(region,k[0],k[1],clean(r.get('bldg_nm')),k[3])]+=1; continue
        if by_id[cid]['region']!=region: raise DataError('거래 자치구와 단지 자치구 불일치: '+by_id[cid]['name'])
        connected.add(cid)
        if clean(r.get('rtrcn_day')) not in ('','-','0'): stats['cancelled']+=1; continue
        try:
            price=int(clean(r['thing_amt']).replace(',','')); area=float(r['arch_area']); floor=int(r['flr'])
        except (ValueError,KeyError,TypeError): raise DataError('연결 거래 수치 필드 오류') from None
        if price<=0 or not 0<area<2000 or not -10<=floor<=200: raise DataError('연결 거래 수치 범위 오류')
        by_id[cid]['tx'].append([date,area,floor,price,k[0],'',k[1]]); stats['saved']+=1
    # 구별로 월 전체가 사라진 경우 발행하지 않는다. 신규 구의 조용한 단지와 구 전체 누락을 구분하기 위한 안전장치다.
    missing=[f'{r}:{m}' for r in loaded_regions for m in months if not region_counts[(r,m)]]
    if missing: raise DataError('아파트 원자료가 통째로 없는 자치구/월이 있습니다: '+', '.join(missing[:6]))
    for cid,c in by_id.items():
        c['tx'].sort(key=lambda t:(t[0],t[1],t[2],t[3]))
        c['data_status']='collected' if c['tx'] else ('no_active_trades' if cid in connected else 'matching_unconfirmed')
        c['trade_source']='서울시 공개 실거래(국토교통부 연계)'
        c['coverage_from']=start if preserve_older else effective_start; c['coverage_to']=end
    meta={'status':'live','provider':'seoul_public','source_verified':True,'updated_at':now(),
          'current_month':end,'min_month':start if preserve_older else effective_start,
          'loaded_regions':loaded_regions,'complex_count':len(by_id),'minimum_households':int(settings.get('minimum_households',300)),
          'metadata_status':'refreshed','refreshed_from':effective_start,'metadata_checked_at':now(),
          'older_history_frozen':bool(preserve_older and start<effective_start),
          'schedule':'매월 1일 04:00 Asia/Seoul','sources':{'trades':TRADES,'metadata':MASTER},
          'note':'매월 공식 공개자료 재수집. 취소 거래/분양권/입주권/임대전용/300세대 미만 제외. 법정동·지번·단지명·건축연도 엄격 연결. 용적률·전세 갭 미지원.'}
    d={'meta':meta,'complexes':list(by_id.values())}; validate_dataset(d,settings)
    if stats['saved']==0: raise DataError('대상 거래 연결 0건')
    for cid,c in by_id.items():
        before=sum(effective_start<=t[0][:7]<=end for t in old_by_id.get(cid,{}).get('tx',[]))
        after=sum(effective_start<=t[0][:7]<=end for t in c['tx'])
        if preserve_older and before>=10 and after<before*.5: raise DataError('단지 거래 급감: '+c['name']+' — 연결/취소 자료 확인 필요')
    unresolved=[{'id':c['id'],'region':c['region'],'name':c['name'],'reason':'연결 가능한 거래 없음(거래 없음·재건축·이름/지번 변경 여부 확인 필요)'} for c in by_id.values() if c['data_status']=='matching_unconfirmed']
    report={'status':'success','published':True,'finished_at':now(),'complex_count':len(by_id),'trade_count':sum(len(c['tx']) for c in by_id.values()),
            'region_complex_counts':dict(collections.Counter(c['region'] for c in by_id.values())),
            'region_trade_counts':dict(collections.Counter(c['region'] for c in by_id.values() for _ in c['tx'])),
            'stats':dict(stats),'raw_month_counts':dict(sorted(counts.items())),'raw_region_month_counts':{f'{r}|{m}':n for (r,m),n in sorted(region_counts.items())},
            'receipt_years':receipt_years,'unresolved_complexes':unresolved,
            'excluded_or_unmatched_buildings':[{'region':k[0],'dong':k[1],'jibun':k[2],'name':k[3],'year':k[4],'count':v} for k,v in sorted(unmapped.items())],
            'notice':'제외/미연결 목록에는 300세대 미만과 대상 외 단지도 포함될 수 있습니다. 이름이 비슷하다는 이유만으로 임의 합치지 않습니다.'}
    return d,report

def run_public(root,fetch=request_bytes,master_rows=None,trade_rows=None,kapt_rows=None):
    root=Path(root); old=read_json(root/'data/site-data.json'); previous=read_json(root/'data/complexes.json')
    try:
        hashes={}
        if master_rows is None: master_rows,hashes['metadata']=download('OA-15818',fetch=fetch)
        settings=read_json(root/'config/settings.json'); regions,_,_=region_maps(settings)
        exclusions=read_json(root/'config/catalog-exclusions.json'); blocked={x['id'] for x in exclusions}
        catalog=normalize_master([r for r in master_rows if clean(lower(r).get('apt_cd')) not in blocked],previous,settings)
        if kapt_rows is not None:
            from kapt_public import supplement_seoul
            hashes['kapt_supplemented_ids']=supplement_seoul(catalog,kapt_rows)
        if trade_rows is None:
            trade_rows=[]
            min_trade_rows=int(settings.get('minimum_expected_trade_rows_per_region',1) or 1)
            for spec in regions:
                part,h=download('OA-21275',spec['code'],fetch)
                # 필터 요청이 무시되거나 다른 자치구 자료가 섞여도 전체 서울 코드라면 collect()만으로는 놓칠 수 있다.
                # 다운로드 직후 해당 자치구 코드 하나만 들어왔는지 확인한다.
                part_codes={clean(lower(r).get('cgg_cd')) for r in part}
                if part_codes!={str(spec['code'])}:
                    raise DataError(f"{spec['name']} 실거래 자치구 필터 응답 오류: {sorted(part_codes)}")
                if len(part)<min_trade_rows:
                    raise DataError(f"{spec['name']} 실거래 원자료 급감({len(part)}건 < {min_trade_rows}건): 기존 데이터 유지")
                trade_rows.extend(part); hashes['trades_'+spec['code']]=h
        elif isinstance(trade_rows,dict):
            trade_rows=[row for spec in regions for row in trade_rows.get(spec['code'],trade_rows.get(spec['name'],[]))]
        end=last_closed_month()
        d,report=collect(catalog,trade_rows,read_json(root/'config/seoul-bindings.json'),old,settings['start_month'],end,settings)
        # Reuse shared official exports/annual archives within this run only.
        cache={}
        def cached_fetch(url,data=None):
            key=(url,data)
            if key not in cache:cache[key]=fetch(url,data)
            return cache[key]
        feature_reports={};region_meta={}
        try:
            for spec in regions:
                subset={'meta':copy.deepcopy(d['meta']),'complexes':[c for c in d['complexes'] if c['region']==spec['name']]}
                if len(regions)==1 and spec['code']=='11560':
                    feature_reports[spec['name']]=enrich(root,subset,cached_fetch)
                else:
                    feature_reports[spec['name']]=enrich(root,subset,cached_fetch,region_code=spec['code'],region_name=spec['name'])
                region_meta[spec['name']]=subset['meta']
            d['meta'].update(features={'far':True,'gap':True},feature_sources=next(iter(region_meta.values()))['feature_sources'],
                far_verified_count=sum(m['far_verified_count'] for m in region_meta.values()),
                jeonse_rows=sum(m['jeonse_rows'] for m in region_meta.values()),jeonse_from=d['meta']['min_month'],jeonse_to=end,
                feature_update={'status':'success','checked_at':now()},region_feature_counts={r:{'far_verified':m['far_verified_count'],'jeonse_rows':m['jeonse_rows']} for r,m in region_meta.items()})
            d['meta']['note']='·'.join(d['meta']['loaded_regions'])+' 300세대 이상. 매매·순수 전세 공식 자료. 용적률은 주소·세대수 일치 대장 검증값만 사용. 미확인 단지는 별도 표시.'
        except DataError as error:
            # A newly added district must never be labelled supported using another district's old features.
            prior={c['id']:c for c in old.get('complexes',[])}
            if not all(old.get('meta',{}).get('features',{}).get(f) for f in ('far','gap')) or any(c['id'] not in prior for c in d['complexes']):raise
            for c in d['complexes']:
                for key in ('far','far_info','far_source','jeonse_tx','jeonse_status'):c[key]=copy.deepcopy(prior[c['id']].get(key,[] if key=='jeonse_tx' else None))
            for key in ('features','feature_sources','far_verified_count','jeonse_rows','jeonse_from','jeonse_to','region_feature_counts'):d['meta'][key]=copy.deepcopy(old['meta'].get(key))
            d['meta']['feature_update']={'status':'preserved','checked_at':old['meta'].get('feature_update',{}).get('checked_at'),'attempted_at':now(),'reason':str(error)}
            feature_reports={'status':'preserved','reason':str(error)}
        report['features']=feature_reports
        report['source_sha256']=hashes; report['catalog_exclusions']=exclusions; d['meta']['catalog_exclusions']=exclusions
        html=embedded_html((root/'index.html').read_text(encoding='utf-8'),d)
        atomic_json(root/'data/site-data.previous.json',old)
        atomic_json(root/'data/site-data.json',d); atomic_json(root/'data/complexes.json',catalog)
        temp=root/'index.html.tmp'; temp.write_text(html,encoding='utf-8'); os.replace(temp,root/'index.html')
        atomic_json(root/'reports/update-report.json',report)
        regions_text='·'.join(d['meta']['loaded_regions'])
        print(f"서울시 공식 자료 수집 완료({regions_text}): {report['complex_count']}개 단지 / {report['trade_count']}건 / 미연결 {len(report['unresolved_complexes'])}개",flush=True)
        return report
    except (DataError,ValueError,KeyError,TypeError) as e:
        msg=str(e) if isinstance(e,DataError) else '응답 형식 또는 파일 검증 오류: 기존 데이터 유지'
        atomic_json(root/'reports/update-report.json',{'status':'failed','published':False,'finished_at':now(),'error':msg})
        raise DataError(msg) from None
