"""K-apt 공개 게시판 전국 기본정보. 로그인 없이 공개된 첨부 파일만 사용."""
import collections, copy, datetime as dt, hashlib, io, json, os, re, urllib.parse, urllib.request, http.cookiejar, zipfile
import xml.etree.ElementTree as ET
from pipeline import DataError, now, norm

KAPT_INFO_PAGE="https://www.data.go.kr/data/15073271/fileData.do"
BOARD="https://www.k-apt.go.kr/web/board/webReference/boardList.do"
def clean(v): return '' if v is None else str(v).strip()

def keynorm(v): return re.sub(r'[\s_\-()/]+','',clean(v)).lower()

def _field(row,*names):
    m={keynorm(k):v for k,v in row.items()}
    for n in names:
        v=m.get(keynorm(n))
        if v is not None and clean(v): return clean(v)
    return ''


def _col_index(ref):
    letters=re.match(r'[A-Z]+',ref or '')
    if not letters: return 0
    n=0
    for ch in letters.group(0): n=n*26+ord(ch)-64
    return n-1


def xlsx_rows(blob,fields=None):
    """표준 라이브러리만으로 첫 워크시트를 읽는다. 제목행이 있어도 헤더행을 탐색한다."""
    if not blob.startswith(b'PK'):
        raise DataError('K-apt 기본정보가 XLSX가 아님: 기존 데이터 유지')
    try:
        z=zipfile.ZipFile(io.BytesIO(blob))
        names=set(z.namelist())
        shared=[]
        if 'xl/sharedStrings.xml' in names:
            root=ET.fromstring(z.read('xl/sharedStrings.xml'))
            ns={'m':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
            for si in root.findall('m:si',ns):
                shared.append(''.join(t.text or '' for t in si.findall('.//m:t',ns)))
        sheets=sorted(n for n in names if n.startswith('xl/worksheets/sheet') and n.endswith('.xml'))
        if not sheets: raise DataError('K-apt XLSX 워크시트 없음')
        ns={'m':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
        out=[];headers=None;row_number=0
        with z.open(sheets[0]) as stream:
            for event,row in ET.iterparse(stream,events=('end',)):
                if row.tag!='{'+ns['m']+'}row':continue
                vals={}
                for c in row.findall('m:c',ns):
                    idx=_col_index(c.get('r',''));typ=c.get('t','')
                    if typ=='inlineStr':val=''.join(t.text or '' for t in c.findall('.//m:t',ns))
                    else:
                        v=c.find('m:v',ns);raw='' if v is None else (v.text or '')
                        if typ=='s' and raw:
                            try:val=shared[int(raw)]
                            except (ValueError,IndexError):raise DataError('K-apt 공유 문자열 참조 오류') from None
                        else:val='1' if typ=='b' and raw=='1' else '0' if typ=='b' else raw
                    vals[idx]=val
                row.clear();row_number+=1
                if not vals:continue
                vector=[vals.get(i,'') for i in range(max(vals)+1)]
                if headers is None:
                    keys={keynorm(x) for x in vector}
                    if all(keynorm(x) in keys for x in ('단지코드','세대수','시도')):headers=[clean(x) for x in vector]
                    elif row_number>=20:raise DataError('K-apt XLSX 헤더 변경')
                    continue
                d={headers[i]:vals.get(i,'') for i in range(len(headers)) if headers[i] and (fields is None or headers[i] in fields)}
                if any(clean(v) for v in d.values()):out.append(d)
        if headers is None:raise DataError('K-apt XLSX 헤더 없음')
        return out
    except DataError: raise
    except (zipfile.BadZipFile,ET.ParseError,KeyError,IndexError,ValueError) as e:
        raise DataError('K-apt XLSX 파싱 오류: 기존 데이터 유지') from None





def find_attachment(listing):
    options=[]
    for hit in re.finditer(r'<(li|tr)\b[^>]*>.*?</\1>',listing,re.S):
        part=hit.group(0)
        if '관리비공개의무단지' not in part or '기본정보' not in part:continue
        file=re.search(r"fileDown\(['\"](\d+)['\"],\s*['\"]03['\"],\s*['\"](\d+)['\"]",part)
        date=re.search(r'(20\d{2})[.-](\d{2})[.-](\d{2})',part)
        if file and date:options.append(('-'.join(date.groups()),file[1],file[2]))
    if not options:raise DataError('K-apt 기본정보 게시물 없음')
    date,seq,num=max(options)
    return seq,num,date

def download_kapt():
    client=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    client.addheaders=[('User-Agent','Mozilla/5.0 k-apt-public/27')]
    try:
        page=client.open(BOARD,timeout=45).read().decode()
        token=re.search(r'<meta[^>]+name="_csrf"[^>]+content="([^"]+)"',page)
        if not token: token=re.search(r'name="_csrf"\s+value="([^"]+)"',page)
        if not token: raise DataError('K-apt 공개 게시판 형식 변경')
        def post(url,args):
            args=dict(args,_csrf=token[1])
            req=urllib.request.Request(url,urllib.parse.urlencode(args).encode(),headers={'Referer':BOARD,'X-CSRF-TOKEN':token[1]})
            return client.open(req,timeout=60).read()
        listing=post('https://www.k-apt.go.kr/web/board/webReference/boardListAjax.do',{'scode':'01','boardType':'03','pageNo':'1','stype':'all','keyword':''}).decode()
        seq,file_number,metadata_date=find_attachment(listing)
        url='https://www.k-apt.go.kr/board/getFileDownload.do?seq='+seq+'&boardType=03'
        blob=post(url,{'file_num':file_number}); rows=xlsx_rows(blob,fields={'시도','시군구','읍면','동리','단지코드','단지명','단지분류','법정동주소','도로명주소','분양형태','사용승인일','세대수','최고층수','최고층수(건축물대장상)'})
        if len(rows)<10000:raise DataError('K-apt 전국 기본정보 급감')
        return rows,{'metadata_date':metadata_date,'url':url,'sha256':hashlib.sha256(blob).hexdigest(),'rows':len(rows),'checked_at':now()}
    except DataError:raise
    except (ValueError,OSError,urllib.error.URLError):raise DataError('K-apt 공개 기본정보 다운로드 실패: 이전 자료 유지') from None


def legal_parcels(row):
    dong=clean(row.get('동리')); eup=clean(row.get('읍면')); addr=clean(row.get('법정동주소'))
    place=' '.join(x for x in [eup,dong] if x)
    if not place:return []
    out=[]
    for part in addr.split(','):
        m=re.search(re.escape(place)+r'\s+(산\s*)?(\d{1,4})(?:-(\d{1,4}))?(?=\s|$)',part)
        if m:
            out.append(('2' if m[1] else '1',str(int(m[2]))+('-'+str(int(m[3])) if m[3] and int(m[3]) else '')))
    return sorted(set(out))


def supplement_seoul(catalog,rows):
    """동일 K-apt 코드·구·법정동·세대수·준공연도가 일치한 누락 지번만 보강."""
    index={clean(r.get('단지코드')):r for r in rows if r.get('시도')=='서울특별시'}
    changes=[]
    for c in catalog:
        r=index.get(c['id'])
        if not r or c.get('metadata_jibun'):continue
        try:hh=int(float(r.get('세대수') or 0));year=int(clean(r.get('사용승인일'))[:4])
        except (ValueError,TypeError):continue
        if (r.get('시군구')!=c['region'] or r.get('동리')!=c.get('legal_dong') or hh!=c['households'] or year!=c.get('build_year')):continue
        parcels=legal_parcels(r)
        if len(parcels)!=1 or parcels[0][0]!='1':continue
        c.update(metadata_jibun=parcels[0][1],metadata_jibun_evidence='kapt_same_id_district_dong_households_year',metadata_parcel_source=KAPT_INFO_PAGE)
        changes.append(c['id'])
    return changes


def normalize_gyeonggi(rows,cities,previous=()):
    out=[];held=[];old={c['id']:c for c in previous};seen={}
    groups=collections.defaultdict(list)
    for row in rows:groups[clean(row.get('단지코드'))].append(row)
    conflict_ids={cid for cid,rs in groups.items() if len({tuple(clean(r.get(k)) for k in ('단지명','세대수','사용승인일','분양형태','시도','시군구')) for r in rs})>1}
    for r in rows:
        if r.get('시도')!='경기도':continue
        district=clean(r.get('시군구'));region=next((x for x in cities if district.startswith(x.removesuffix('시'))),'')
        if not region:continue
        try:hh=int(float(r.get('세대수') or 0))
        except (ValueError,TypeError):raise DataError('경기도 세대수 형식 변경') from None
        if hh<300:continue
        if r.get('단지분류') not in ('아파트','주상복합') or r.get('분양형태') not in ('분양','혼합'):continue
        cid=clean(r.get('단지코드'));name=clean(r.get('단지명'));date=clean(r.get('사용승인일'))
        if not cid or not name:raise DataError('경기도 단지 코드/명 누락')
        if cid in seen:continue
        seen[cid]=True
        if cid in conflict_ids:held.append({'id':cid,'name':name,'region':region,'reason':'동일 관리코드 기본정보 충돌'});continue
        try:year=int(date[:4]);dt.date(int(date[:4]),int(date[4:6]),int(date[6:8]))
        except (ValueError,TypeError):held.append({'id':cid,'name':name,'region':region,'reason':'사용승인일 확인 필요'});continue
        parcels=legal_parcels(r)
        if len(parcels)>1:
            held.append({'id':cid,'name':name,'region':region,'reason':'여러 지번/세부 단지 합산 세대수: 각각 300세대 이상인지 확인 필요'});continue
        dong=' '.join(x for x in [clean(r.get('읍면')),clean(r.get('동리'))] if x)
        c=copy.deepcopy(old.get(cid,{}))
        c.update(id=cid,region=region,name=c.get('name') or name,official_name=name,households=hh,address=clean(r.get('도로명주소')),legal_address=clean(r.get('법정동주소')),legal_dong=dong,district=district,metadata_parcels=[list(p) for p in parcels],metadata_jibun=parcels[0][1] if len(parcels)==1 else '',metadata_source=KAPT_INFO_PAGE,metadata_checked_at=now(),metadata_type=r['단지분류'],tenure=r['분양형태'],completed=date[:4]+'.'+date[4:6],build_year=year)
        c['aliases']=sorted(set(c.get('aliases',[])+[name,c['name']]))
        c['region_tags']=gyeonggi_region_tags(c)
        c.setdefault('station','');c.setdefault('station_display','');c.setdefault('naver','https://new.land.naver.com/search?sk='+urllib.parse.quote(c['name']))
        try:c['top_floor']=int(float(r.get('최고층수(건축물대장상)') or r.get('최고층수') or 0)) or None
        except (ValueError,TypeError):c['top_floor']=None
        c.update(far=None,far_info={'status':'unconfirmed','value':None,'reason':'경기도 용적률 대장 수치 미확보','source':KAPT_INFO_PAGE},far_source='',jeonse_contract_kind_available=False)
        c.pop('tx',None);c.pop('jeonse_tx',None);c.pop('trade_binding_note',None);c.pop('trade_binding_methods',None);out.append(c)
    counts=collections.Counter(c['region'] for c in out)
    for city in cities:
        before=sum(c.get('region')==city for c in previous)
        if counts[city]<max(5,int(before*.8)):raise DataError(city+' 대상 단지 목록 급감')
    return sorted(out,key=lambda c:(c['region'],c['id'])),held


def gyeonggi_region_tags(c):
    region=c['region'];district=c.get('district','');tags=[region]
    suffix=district.removeprefix(region.removesuffix('시')).removeprefix('시')
    if suffix.endswith('구'):tags.append(suffix)
    if suffix=='동탄구':tags.append('동탄시')
    if c.get('legal_dong')=='평촌동':tags.append('평촌동')
    return list(dict.fromkeys(tags))
