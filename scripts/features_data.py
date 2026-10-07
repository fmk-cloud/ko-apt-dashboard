"""Official FAR and pure-jeonse collection, isolated from the sale-price algorithm."""
import collections,csv,datetime as dt,hashlib,io,json,math,re,urllib.parse,zipfile
from pathlib import Path
from pipeline import DataError,now,norm,month_range,read_json,atomic_json

RENT_PAGE='https://data.seoul.go.kr/dataList/OA-21276/A/1/datasetView.do'
FAR_PAGE='https://data.seoul.go.kr/dataList/OA-23051/S/1/datasetView.do'
EXPORT='https://datafile.seoul.go.kr/bigfile/iot/sheet/json/download.do'
ARCHIVE='https://datafile.seoul.go.kr/bigfile/iot/inf/nio_download.do?&useCache=false'
FIELDS={'접수년도':'rcpt_yr','자치구코드':'cgg_cd','법정동코드':'stdg_cd','법정동명':'stdg_nm','본번':'mno','부번':'sno','층':'flr','계약일':'ctrt_day','전월세구분':'rent_se','임대면적':'rent_area','보증금(만원)':'grfe','임대료(만원)':'rtfe','건물명':'bldg_nm','건축년도':'arch_yr','건물용도':'bldg_usg','계약기간':'ctrt_prd','신규계약구분':'new_updt_yn','갱신청구권사용':'ctrt_updt_use_yn','종전보증금':'bfr_grfe','종전임대료':'bfr_rtfe'}
def clean(v):return '' if v is None else str(v).strip()
def number(v):
 try:
  n=float(clean(v).replace(',',''));return n if math.isfinite(n) else None
 except ValueError:return None

def download_rows(dataset,fetch,allow_empty=False,region_code="11560"):
 params={'srvType':'S','infId':dataset,'serviceKind':'1','pageNo':'1','ssUserId':'SAMPLE_VIEW','strWhere':'','strOrderby':'','filterCol':'CGG_CD' if dataset=='OA-21276' else '', 'txtFilter':region_code if dataset=='OA-21276' else ''}
 blob=fetch(EXPORT,urllib.parse.urlencode(params).encode())
 try:obj=json.loads(blob)
 except (ValueError,UnicodeDecodeError):raise DataError('전세/용적률 공개자료 JSON 해석 실패') from None
 if not isinstance(obj,dict) or not isinstance(obj.get('DATA'),list) or (not obj['DATA'] and not allow_empty):raise DataError('전세/용적률 공개자료 DATA 누락')
 return [{k.lower():v for k,v in r.items()} for r in obj['DATA']],hashlib.sha256(blob).hexdigest()

def archive_index(html):
 out={}
 for block in re.findall(r'<tr\b[^>]*>.*?</tr>',html,re.S):
  y=re.search(r'서울특별시_전월세가_(\d{4})\.zip',block);seq=re.search(r"downloadFile\('([0-9]+)'\)",block)
  if y and seq:
   stamp=re.search(r'(20\d{2}\.\d{2}\.\d{2}\.)',block)
   out[int(y[1])]={'seq':seq[1],'published':stamp[1] if stamp else ''}
 return out

def read_archive(blob,region_code="11560"):
 try:
  with zipfile.ZipFile(io.BytesIO(blob)) as z:
   csvs=[n for n in z.namelist() if n.lower().endswith('.csv')]
   if len(csvs)!=1:raise DataError('전세 연도 파일의 CSV 구성 변경')
   raw=z.read(csvs[0])
 except (zipfile.BadZipFile,RuntimeError):raise DataError('전세 연도 ZIP 해석 실패') from None
 text=None
 for encoding in ('utf-8-sig','cp949'):
  try:text=raw.decode(encoding);break
  except UnicodeDecodeError:pass
 if text is None:raise DataError('전세 CSV 문자 인코딩 변경')
 reader=csv.DictReader(io.StringIO(text))
 if not set(FIELDS).issubset(reader.fieldnames or []):raise DataError('전세 CSV 필드 변경')
 return [{v:r[k] for k,v in FIELDS.items()} for r in reader if clean(r['자치구코드'])==region_code]

def road(address):
 m=re.search(r'([가-힣A-Za-z0-9·]+(?:대로|로|길))\s+(\d+)(?:-(\d+))?',address)
 return (m[1],int(m[2]),int(m[3] or 0)) if m else None

def assign_far(catalog,rows,bindings,region_name="영등포구"):
 district=[r for r in rows if clean(r.get('sgg_cd_nm'))=='서울특별시 '+region_name]
 if len(district)<100:raise DataError('용적률 원자료 '+region_name+' 범위 급감')
 result=[];verified=0
 for c in catalog:
  parcels={(b['legal_dong'],b['jibun']) for b in bindings if b['complex_id']==c['id']}
  rk=road(c['address']);matches=[]
  for r in district:
   try:
    parcel=str(int(r['mn_lotno']))+('-'+str(int(r['sub_lotno'])) if int(r['sub_lotno'] or 0) else '')
    rr=(r['na_road_cd_nm'],int(r['na_mn_lotno'] or 0),int(r['na_sub_lotno'] or 0))
   except (ValueError,TypeError,KeyError):continue
   if (r['stdg_cd_nm'],parcel) in parcels or (rk and rr==rk and r['stdg_cd_nm']==c['legal_dong']):matches.append(r)
  # Prefer a full-complex residential ledger. Never average ratios of individual buildings.
  candidates=[]
  for r in matches:
   hh=number(r.get('hh_cnt'));yr=clean(r.get('use_aprv_ymd'))[:4]
   if hh is None or abs(hh-c['households'])>max(5,c['households']*.01):continue
   if yr.isdigit() and abs(int(yr)-c.get('build_year',0))>2:continue
   if '공동주택' not in clean(r.get('mn_usg_cd_nm')) and '아파트' not in clean(r.get('etc_usg_cn')):continue
   candidates.append(r)
  record={'status':'unconfirmed','value':None,'checked_at':now(),'source':FAR_PAGE,'reason':'대지·세대수 일치 대장 없음' if matches else '단지와 일치하는 총괄표제부 없음'}
  if len(candidates)==1:
   r=candidates[0];f=number(r.get('fart'));a=number(r.get('siar'));g=number(r.get('fart_cmpttn_gfa'))
   record.update(ledger_id=str(r['bdrg_sn']),address=r['plat_plc'],ledger_households=r['hh_cnt'])
   if f is not None and 0<f<=2000:
    if a and g and abs(g/a*100-f)>max(.1,.01*f):record['reason']='대장 용적률과 산정면적 비율 불일치'
    else:record.update(status='verified',value=f,reason='주소·세대수 일치 총괄표제부');verified+=1
   else:record['reason']='공식 용적률 값 없음 또는 0'
  elif len(candidates)>1:record['reason']='동일 단지 대장이 여러 개: 확인 필요'
  c['far']=record['value'];c['far_info']=record;c['far_source']='서울시 건축물대장 총괄표제부' if record['value'] is not None else ''
  result.append({'id':c['id'],'name':c['name'],**record})
 if not verified:raise DataError('확인 가능한 용적률 0개')
 return {'verified':verified,'total':len(catalog),'checked_at':now(),'items':result,'source':FAR_PAGE}

def parcel_key(r):
 a=int(r['mno']);b=int(r.get('sno') or 0)
 return str(a)+('-'+str(b) if b else '')

def collect_rent(catalog,rows,bindings,start,end,region_code="11560"):
 byid={c['id']:c for c in catalog};idx={};counts=collections.Counter();stats=collections.Counter();seen=set();unmatched=collections.Counter()
 for b in bindings:
  if b['complex_id'] in byid:idx[(b['legal_dong'],b['jibun'],norm(b['trade_name']),b['build_year'])]=b['complex_id']
 out={cid:[] for cid in byid}
 for r in rows:
  if clean(r.get('cgg_cd'))!=region_code:raise DataError('전세 원자료 자치구 범위 오류')
  if clean(r.get('bldg_usg'))!='아파트':continue
  if clean(r.get('rent_se'))!='전세':stats['monthly_rent_excluded']+=1;continue
  monthly=number(r.get('rtfe'))
  if monthly is None:raise DataError('전세 자료 임대료 필드 확인 불가')
  if monthly!=0:stats['monthly_rent_excluded']+=1;continue
  date=clean(r.get('ctrt_day'))
  try:date=dt.datetime.strptime(date,'%Y%m%d').date().isoformat()
  except ValueError:raise DataError('전세 계약일 형식 변경') from None
  if not start<=date[:7]<=end:continue
  counts[date[:7]]+=1
  try:k=(clean(r.get('stdg_nm')),parcel_key(r),norm(clean(r.get('bldg_nm'))),int(r.get('arch_yr') or 0))
  except (ValueError,TypeError,KeyError):stats['unidentified_address']+=1;continue
  cid=idx.get(k)
  if not cid:
   candidates=[c for c in catalog if c['legal_dong']==k[0] and c['build_year']==k[3] and k[2] in {norm(c['name']),norm(c.get('official_name',''))}]
   if len(candidates)==1 and k[1] in {b['jibun'] for b in bindings if b['complex_id']==candidates[0]['id']}:cid=candidates[0]['id']
  if not cid:unmatched[k]+=1;continue
  area=number(r.get('rent_area'));deposit=number(r.get('grfe'));floor=number(r.get('flr'))
  if area is None or deposit is None or not 0<area<2000 or deposit<=0:raise DataError('연결 전세 수치 오류')
  if floor is not None and (floor!=int(floor) or not -10<=floor<=200):raise DataError('전세 층수 오류')
  kind=clean(r.get('new_updt_yn')) or '미상';right=clean(r.get('ctrt_updt_use_yn'))
  # Sources do not expose a unique contract ID. Collapse identical disclosed full rows and label counts as distinct data rows.
  fingerprint=(cid,date,area,floor,deposit,k[1],kind,right,clean(r.get('ctrt_prd')),clean(r.get('bfr_grfe')),clean(r.get('bfr_rtfe')))
  if fingerprint in seen:stats['identical_public_rows_removed']+=1;continue
  seen.add(fingerprint)
  out[cid].append([date,area,int(floor) if floor is not None else None,int(deposit),kind,right,clean(r.get('ctrt_prd'))])
 for c in catalog:
  c['jeonse_tx']=sorted(out[c['id']],key=lambda t:(t[0],t[1],t[2] if t[2] is not None else -999,t[3],t[4]))
  c['jeonse_status']='collected' if c['jeonse_tx'] else 'no_matched_records'
 total=sum(map(len,out.values()))
 if total==0:raise DataError('대상 단지 전세 연결 0행')
 return {'rows':total,'complexes_with_rent':sum(bool(v) for v in out.values()),'stats':dict(stats),'raw_month_counts':dict(sorted(counts.items())), 'source':RENT_PAGE,'checked_at':now(),'note':'공개 전세 자료에는 계약해제 필드가 없어 개별 해제 여부는 확인 불가. 동일 공개행 중복 제거 후 자료 행 수를 표시.'}

def enrich(root,d,fetch,fixtures=None,region_code="11560",region_name="영등포구"):
 """Prepare every feature before the caller publishes files; yearly archives are refreshed too."""
 root=Path(root);cs=d['complexes'];bindings=read_json(root/'config/seoul-bindings.json');start=d['meta']['min_month'];end=d['meta']['current_month'];hashes={}
 if fixtures:
  far,live,archives=fixtures['far'],fixtures['live'],fixtures['archives'];listed=fixtures.get('archive_index',{y:{'published':'fixture'} for y in archives});current_year=fixtures.get('current_year',dt.date.today().year)
 else:
  far,hashes['far']=download_rows('OA-23051',fetch)
  html=fetch(RENT_PAGE).decode('utf-8');listed=archive_index(html)
  if not listed:raise DataError('전세 연도 파일 목록 확인 실패')
  current_year=int(now()[:4]);live,hashes['rent_current']=download_rows('OA-21276',fetch,allow_empty=current_year>int(end[:4]),region_code=region_code);archives={}
  for year in range(int(start[:4]),min(current_year,int(end[:4])+1)):
   if year not in listed:raise DataError(f'{year}년 전세 연도파일이 아직 공개되지 않았습니다. 기존 정상 자료 유지')
   params={'infId':'OA-21276','infSeq':'3','seq':listed[year]['seq'],'seqNo':''}
   blob=fetch(ARCHIVE,urllib.parse.urlencode(params).encode());hashes['rent_'+str(year)]=hashlib.sha256(blob).hexdigest();archives[year]=read_archive(blob,region_code)
 far_report=assign_far(cs,far,bindings,region_name)
 rows=[r for yy,rr in archives.items() for r in rr]+live
 report=collect_rent(cs,rows,bindings,start,end,region_code)
 missing=[m for m in month_range(start,end) if not report['raw_month_counts'].get(m)]
 if missing:raise DataError('전세 원자료 월 전체 누락: '+', '.join(missing))
 old=read_json(root/'data/site-data.json')
 if old.get('meta',{}).get('features',{}).get('gap'):
  prior={c['id']:c for c in old['complexes']}
  for c in cs:
   before=sum(start<=t[0][:7]<=end for t in prior.get(c['id'],{}).get('jeonse_tx',[]))
   if before>=10 and len(c['jeonse_tx'])<before*.5:raise DataError('단지 전세 자료 급감: '+c['name'])
 report['archives']={str(y):listed[y] for y in archives};report['current_receipt_year']=current_year
 d['meta']['feature_sources']={'far':FAR_PAGE,'jeonse':RENT_PAGE};d['meta']['features']={'far':True,'gap':True}
 d['meta']['far_verified_count']=far_report['verified'];d['meta']['jeonse_rows']=report['rows'];d['meta']['jeonse_from']=start;d['meta']['jeonse_to']=end
 d['meta']['note']=region_name+' 300세대 이상. 용적률 공식 대장 검증값, 전세는 순수 전세 공개자료. 미확인 값은 제외 또는 별도 표시.'
 return {'far':far_report,'jeonse':report,'sha256':hashes}
