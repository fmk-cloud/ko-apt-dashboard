"""경기부동산포털 공개 아파트 실거래 화면의 자료. 공개 세션과 CSRF만 사용.
매매/전세/월세가 한 표 행에 나란히 있으므로 각각 독립적으로 처리한다.
"""
import collections,copy,datetime as dt,hashlib,http.cookiejar,json,re,threading,time,urllib.parse,urllib.request,urllib.error
from concurrent.futures import ThreadPoolExecutor,as_completed
from pathlib import Path
from pipeline import DataError,norm,now,atomic_json,month_range
BASE='https://gris.gg.go.kr'
VIEW=BASE+'/rtlp/selectRtlpView.do'
CITIES=['성남시','과천시','안양시','화성시','광명시']
def clean(v):return '' if v is None else str(v).strip()
class PublicClient:
    def __init__(self):
        self.client=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        self.client.addheaders=[('User-Agent','Mozilla/5.0 k-apt-public/27')]
        try:html=self.client.open(VIEW,timeout=35).read().decode()
        except (OSError,urllib.error.URLError):raise DataError('경기도 공개 실거래 화면 접속 실패') from None
        hit=re.search(r'name="_csrf"\s+value="([^"]+)"',html)
        if not hit:raise DataError('경기도 공개 화면 형식 변경')
        self.token=hit[1]
    def post(self,path,args,timeout=50):
        args=dict(args,_csrf=self.token)
        req=urllib.request.Request(BASE+path,urllib.parse.urlencode(args).encode(),headers={'Referer':VIEW,'X-CSRF-TOKEN':self.token,'X-Requested-With':'XMLHttpRequest'})
        for attempt in range(2):
            try:
                b=self.client.open(req,timeout=timeout).read();return json.loads(b),b
            except urllib.error.HTTPError as error:
                if error.code not in (408,429,500,502,503,504):raise DataError('경기도 공개 화면 HTTP '+str(error.code)) from None
            except (OSError,urllib.error.URLError,ValueError):pass
            if attempt==0:time.sleep(2)
        raise DataError('경기도 공개 실거래 응답 실패: '+path) from None
    def addresses(self,code=None,old=False):
        endpoint='/cmm/adr/selectOldUmdList.do' if old else '/cmm/adr/selectUmdRiList.do'
        if code is None:endpoint='/cmm/adr/selectOldSigunguList.do' if old else '/cmm/adr/selectSigunguList.do'
        obj,b=self.post(endpoint,{'sggCd':code} if code else {})
        if not isinstance(obj,list) or not obj:raise DataError('경기도 법정동 목록 누락')
        return obj
    def trades(self,code,dong,year,start=None,end=None,old=False):
        cache=getattr(self,'range_cache',None)
        path=Path(cache)/f"{code}-{dong}-{year}-{start or 'annual'}-{end or 'annual'}-{old}.json" if cache else None
        if path and path.exists():
            saved=json.loads(path.read_text());return {'rtlpList':saved['rows']},saved['sha256']
        args={'tabKind':'tab1','aptCd':'','aptNm':'','sggCd':code,'umdCd':dong,'daytype':'DEAL','selDate':'2' if start is None else '1','searchYear':str(year),'startDate':start or f'{year}0101','endDate':end or f'{year}1231','accYear':str(year),'exuseArea1':'0','exuseArea2':'0','minAmount':'','maxAmount':''}
        if old:args['old']='old'
        try:
            obj,b=self.post('/rtlp/selectRtlpList.do',args,timeout=45 if start is None else 60)
            if not isinstance(obj,dict) or not isinstance(obj.get('rtlpList'),list):raise DataError('경기도 실거래 목록 형식 변경')
            h=hashlib.sha256(b).hexdigest()
        except DataError:
            if start is not None and int(start[4:6])==int(end[4:6]):raise
            parts=[];hashes=[]
            if start is None:
                periods=[(f'{year}{a}',f'{year}{b}') for a,b in [('0101','0331'),('0401','0630'),('0701','0930'),('1001','1231')]]
            else:
                import calendar
                periods=[(f'{year}{m:02}01',f'{year}{m:02}{calendar.monthrange(year,m)[1]:02}') for m in range(int(start[4:6]),int(end[4:6])+1)]
            for first,last in periods:
                piece,ph=self.trades(code,dong,year,start=first,end=last,old=old);parts.extend(piece['rtlpList']);hashes.append(ph)
            obj={'rtlpList':parts};h=hashlib.sha256(json.dumps(hashes).encode()).hexdigest()
        if path:atomic_json(path,{'rows':obj['rtlpList'],'sha256':h,'checked_at':now(),'query':{k:v for k,v in args.items() if k!='_csrf'}})
        return obj,h

def query_plan(catalog,client):
    plan=[];unresolved=[];districts=client.addresses();eup_groups={}
    for spec in districts:
        code=clean(spec.get('sggCd'));district=norm(spec.get('sggNm'))
        cats=[c for c in catalog if norm(c['district']).replace('시','')==district.replace('시','')]
        if not cats:continue
        addresses=client.addresses(code)
        for row in addresses:
            dong=clean(row.get('umdNm'));dc=clean(row.get('umdCd'))
            chosen=[c for c in cats if norm(c['legal_dong'])==norm(dong)]
            if chosen:
                eup_hit=re.match(r'^([가-힣0-9]+(?:읍|면))\s+',dong)
                group=(code,eup_hit[1]) if eup_hit else None
                if group and group in eup_groups:
                    eup_groups[group]['ids']=sorted(set(eup_groups[group]['ids']+[c['id'] for c in chosen]));continue
                entry={'code':code,'dong_code':dc,'dong':dong,'region':chosen[0]['region'],'district':clean(spec['sggNm']),'ids':[c['id'] for c in chosen]}
                if group:entry.update(eup_scope=True,eup_name=eup_hit[1]);eup_groups[group]=entry
                plan.append(entry)
    # 화성 구 분리 전 자료는 현재 코드만 조회하면 빠진다. 포털이 제공하는 이전행정구역 조회도 병행한다.
    hwa=[c for c in catalog if c['region']=='화성시']
    if hwa:
        old_districts=[r for r in client.addresses(old=True) if clean(r.get('sggNm'))=='화성시']
        if len(old_districts)!=1:raise DataError('화성 이전행정구역 공식 코드 확인 실패')
        old_code=clean(old_districts[0]['sggCd'])
        for row in client.addresses(old_code,old=True):
            old_dong=clean(row.get('umdNm'));canonical='여울동' if old_dong=='오산동' else old_dong
            eup=old_dong.endswith(('읍','면'))
            chosen=[c for c in hwa if norm(c['legal_dong'])==norm(canonical) or (eup and c['legal_dong'].startswith(old_dong+' '))]
            if chosen:plan.append({'code':old_code,'dong_code':clean(row['umdCd']),'dong':old_dong,'canonical_dong':canonical,'old_eup':eup,'old':True,'region':'화성시','district':'화성시(이전행정구역)','ids':[c['id'] for c in chosen]})
    covered={cid for p in plan for cid in p['ids']}
    unresolved=[c['id'] for c in catalog if c['id'] not in covered]
    for city in sorted({c['region'] for c in catalog}):
        if not any(p['region']==city for p in plan):raise DataError(city+' 공식 법정동 연결 없음')
    return plan,unresolved

def disclosed_date(value,year):
    value=clean(value)
    if not value:return None
    parts=re.findall(r'\d+',value)
    if len(parts)==2:y=year;m,d=map(int,parts)
    elif len(parts)==3:
        y,m,d=map(int,parts);y=y+2000 if y<100 else y
    elif len(parts)==1 and len(parts[0])==8:y,m,d=int(value[:4]),int(value[4:6]),int(value[6:8])
    else:raise DataError('경기도 계약일 형식 변경: '+value)
    try:return dt.date(y,m,d).isoformat()
    except ValueError:raise DataError('경기도 계약일 범위 오류') from None

def row_identity(r):
    pnu=clean(r.get('PNU'))
    if not re.fullmatch(r'\d{19}',pnu):return None
    main=int(pnu[11:15]);sub=int(pnu[15:19]);parcel=str(main)+('-'+str(sub) if sub else '')
    try:year=int(clean(r.get('MVIN_YM'))[:4])
    except ValueError:return None
    return pnu[:5],pnu[5:10],pnu[10],parcel,year,norm(r.get('KAB_APTNM',''))

def value_number(value,integer=False):
    try:n=float(clean(value).replace(',',''));return int(n) if integer and n.is_integer() else n
    except (ValueError,TypeError):raise DataError('경기도 실거래 수치 형식 오류') from None


def canonical_name(value,region):
    s=norm(value).replace('에스케이','sk').replace('엘지','lg')
    prefix=norm(region.removesuffix('시'))
    return s.removeprefix(prefix)


def parcel_name_key(value,c):
    """같은 지번·연도의 명칭에 한정해 접두 지역명, 단지/차 표기와 숫자 위치 정규화."""
    s=norm(value).replace('e편한','이편한').replace('에스케이','sk').replace('엘지','lg')
    for prefix in (norm(c['region'].removesuffix('시')),norm(c.get('legal_dong','')).removesuffix('동')):
        if len(prefix)>=2:s=s.removeprefix(prefix)
    s=s.replace('아파트','').replace('마을','')
    s=re.sub(r'(\d+)(?:단지|차)',r'\1',s)
    numbers=tuple(re.findall(r'\d+',s));letters=re.sub(r'\d+','',s)
    return letters,numbers


def find_complex(candidates,key,region):
    matches=[c for c in candidates if [key[2],key[3]] in c.get('metadata_parcels',[]) and c.get('build_year')==key[4]]
    exact=[c for c in matches if key[5] in {norm(a) for a in c['aliases']}]
    contained=[c for c in matches if any(len(min(key[5],norm(a),key=len))>=4 and (key[5] in norm(a) or norm(a) in key[5]) for a in c['aliases'])]
    chosen=exact if len(exact)==1 else contained if len(contained)==1 else []
    if chosen:return chosen[0],'parcel_name_year'
    equivalent=[c for c in matches if any(parcel_name_key(key[5],c)==parcel_name_key(a,c) for a in c['aliases'])]
    if len(equivalent)==1:return equivalent[0],'parcel_normalized_name_year'
    # 지번이 한쪽 원천에서 제공되지 않는 경우에 한정. 법정동·준공연도·완전한 단지명이 유일하게 일치해야 한다.
    # 양쪽 지번이 있는데 서로 다르거나 이름이 일부만 비슷한 경우에는 적용하지 않는다.
    fallback=[c for c in candidates if c.get('build_year')==key[4] and (key[3]=='0' or not c.get('metadata_parcels'))
              and len(key[5])>=6 and canonical_name(key[5],region) in {canonical_name(a,region) for a in c['aliases']}]
    if len(fallback)==1:return fallback[0],'exact_name_dong_year_missing_parcel'
    return None,None

def collect(catalog,responses,plan,start,end,previous=()):
    by_id={c['id']:dict(copy.deepcopy(c),tx=[],jeonse_tx=[],trade_binding_methods=[]) for c in catalog};stats=collections.Counter();raw_months=collections.Counter();unmatched=collections.Counter();seen=collections.defaultdict(set);connected=set();old={c['id']:c for c in previous}
    pindex={(p['code'],p['dong_code']):p for p in plan}
    for response in responses:
        code=response['code'];dong=response['dong_code'];year=response['year'];p=pindex[(code,dong)]
        candidates=[by_id[cid] for cid in p['ids']]
        for r in response['rows']:
            stats['raw_rows']+=1
            k=row_identity(r)
            if not k:stats['unidentified_rows']+=1;continue
            if k[0]!=code or (k[1]!=dong and not ((p.get('old_eup') or p.get('eup_scope')) and k[1][:3]==dong[:3])):raise DataError('경기도 응답 시군구·법정동 필터 불일치')
            effective_dong=p.get('canonical_dong',p['dong'])
            if p.get('old_eup') or p.get('eup_scope'):
                eup_name=p.get('eup_name',p['dong'])
                disclosed=clean(r.get('UMD_NM')).strip('()（） ')
                if not disclosed or not disclosed.endswith('리'):stats['unconfirmed_legal_ri']+=1;continue
                effective_dong=disclosed if disclosed.startswith(eup_name) else eup_name+' '+disclosed
            scoped_candidates=[c for c in candidates if norm(c['legal_dong'])==norm(effective_dong)]
            if clean(r.get('BLDG_MUSE_CD')) not in ('','02001'):continue
            chosen,method=find_complex(scoped_candidates,k,p['region'])
            cid=chosen['id'] if chosen else None
            for prefix in ('A','B'):
                price_text=clean(r.get(prefix+'21'));date_text=clean(r.get(prefix+'11'))
                if not price_text or not date_text:continue
                date=disclosed_date(date_text,year)
                if int(date[:4])!=year:raise DataError('경기도 연도 검색 응답 기간 불일치')
                if not start<=date[:7]<=end:continue
                raw_months[(p['region'],prefix,date[:7])]+=1
                if not cid:unmatched[(p['region'],r.get('KAB_APTNM'),k[3],k[4])]+=1;continue
                connected.add(cid)
                by_id[cid].setdefault('trade_binding_methods',[])
                if method not in by_id[cid]['trade_binding_methods']:by_id[cid]['trade_binding_methods'].append(method)
                if prefix=='A' and clean(r.get('DPOS_GBN')):stats['cancelled_sale']+=1;continue
                area=value_number(r.get('BLDG_AREA'));price=value_number(price_text,True);floor=value_number(r.get(prefix+'31'),True) if clean(r.get(prefix+'31')) else None
                if not isinstance(price,int) or price<=0 or not 0<area<2000 or (floor is not None and (not isinstance(floor,int) or not -10<=floor<=200)):raise DataError('경기도 거래 수치 범위 오류')
                if prefix=='A' and floor is None:stats['missing_sale_floor']+=1;continue
                t=[date,area,floor,price,by_id[cid]['legal_dong'],'',k[3]] if prefix=='A' else [date,area,floor,price,'미상','','']
                signature=(prefix,*t)
                if signature in seen[cid]:stats['duplicate_disclosed_rows']+=1;continue
                seen[cid].add(signature);by_id[cid]['tx' if prefix=='A' else 'jeonse_tx'].append(t);stats['sale_saved' if prefix=='A' else 'jeonse_saved']+=1
    for c in by_id.values():
        c['tx'].sort(key=lambda t:(t[0],t[1],t[2],t[3]));c['jeonse_tx'].sort(key=lambda t:(t[0],t[1],t[2] if t[2] is not None else -999,t[3]))
        if 'exact_name_dong_year_missing_parcel' in c.get('trade_binding_methods',[]):c['trade_binding_note']='지번 원천 미제공: 법정동·준공연도·완전 일치 단지명으로 연결(시 이름·SK/LG 표기 정규화)'
        c.update(data_status='collected' if c['tx'] else 'no_active_trades' if c['id'] in connected else 'matching_unconfirmed',jeonse_status='collected' if c['jeonse_tx'] else 'no_matched_records',trade_source='경기부동산포털 공개 실거래',jeonse_source=VIEW,coverage_from=start,coverage_to=end)
        before=old.get(c['id'],{})
        for field in ('tx','jeonse_tx'):
            if len(before.get(field,[]))>=10 and len(c[field])<len(before[field])*.5:raise DataError('경기도 단지 거래 급감: '+c['name'])
    for city in sorted({c['region'] for c in catalog}):
        for month in month_range(start,end):
            if raw_months[(city,'A',month)]==0:raise DataError(city+' 매매 원자료 월 전체 누락: '+month)
        if sum(len(c['tx']) for c in by_id.values() if c['region']==city)==0:raise DataError(city+' 거래 연결 0건')
    report={'status':'success','checked_at':now(),'stats':dict(stats),'region_counts':{city:sum(c['region']==city for c in by_id.values()) for city in CITIES},'raw_region_month_counts':{'|'.join(k):n for k,n in sorted(raw_months.items())},'unmatched_buildings':[{'region':k[0],'name':k[1],'parcel':k[2],'year':k[3],'rows':n} for k,n in unmatched.items()],'unresolved_complexes':[{'id':c['id'],'region':c['region'],'name':c['name']} for c in by_id.values() if c['data_status']=='matching_unconfirmed'],'note':'B열 순수전세만 사용. C열 월세 제외. 신규/갱신 구분 원천 미제공. 동일 공개행 중복 제거. 용적률 미확보.'}
    return list(by_id.values()),report

def download_responses(plan,start,end,cache=None,max_workers=3):
    """매년 법정동별 공식 연도 검색. 캐시는 명시적 재현/QA에만 사용; 월별 실수집은 캐시 없이."""
    local=threading.local();jobs=[dict(p,year=y) for p in plan for y in range(int(start[:4]),int(end[:4])+1)];out=[]
    def job(spec):
        path=Path(cache)/f"{spec['code']}-{spec['dong_code']}-{spec['year']}.json" if cache else None
        if path and path.exists():obj=json.loads(path.read_text());obj['cached']=True;return obj
        if not hasattr(local,'client'):
            local.client=PublicClient()
            if cache:local.client.range_cache=Path(cache)/'ranges'
        if spec.get('old_eup') and spec['dong']=='향남읍' and spec['year']<int(end[:4]):
            # 이전 향남읍은 연도·분기 응답이 특히 커서 완료 연도는 월별로 직접 조회한다.
            import calendar
            pieces=[];hashes=[]
            for month in range(1,13):
                piece,ph=local.client.trades(spec['code'],spec['dong_code'],spec['year'],start=f"{spec['year']}{month:02}01",end=f"{spec['year']}{month:02}{calendar.monthrange(spec['year'],month)[1]:02}",old=True)
                pieces.extend(piece['rtlpList']);hashes.append(ph)
            obj={'rtlpList':pieces};h=hashlib.sha256(json.dumps(hashes).encode()).hexdigest()
        else:obj,h=local.client.trades(spec['code'],spec['dong_code'],spec['year'],old=spec.get('old',False))
        record={'code':spec['code'],'dong_code':spec['dong_code'],'year':spec['year'],'rows':obj['rtlpList'],'source':VIEW,'sha256':h,'checked_at':now(),'old':spec.get('old',False)}
        if path:atomic_json(path,record)
        return record
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures={pool.submit(job,s):s for s in jobs}
        for i,f in enumerate(as_completed(futures),1):
            try:result=f.result()
            except Exception:
                for pending in futures:pending.cancel()
                failed=futures[f]
                raise DataError(f"경기 수집 실패 {failed['region']} {failed['dong']} {failed['year']}: 이전 데이터 유지") from None
            out.append(result);s=futures[f]
            if result.get('cached'):continue
            print(f"경기 수집 {i}/{len(jobs)} {s['region']} {s['dong']} {s['year']} {len(result['rows'])}행",flush=True)
    return out
