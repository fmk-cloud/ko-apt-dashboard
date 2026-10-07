"""공식 단지 좌표 + 공개 보행망으로 역 연결. 실패하면 기존 역 자료 보존."""
import argparse,copy,datetime as dt,hashlib,http.cookiejar,json,os,re,subprocess,sys,tempfile,urllib.parse,urllib.request
from pathlib import Path
from pipeline import read_json,atomic_json,validate_dataset,now,last_closed_month,DataError
from dataset_storage import publish_bundle
PAGE='https://www.k-apt.go.kr/kaptinfo/openKaptMng.do'
PBF='https://download.geofabrik.de/asia/south-korea-latest.osm.pbf'

def apply_transport(d,links):
 out=copy.deepcopy(d)
 for c in out['complexes']:
  row=links['complexes'].get(c['id'])
  if row is None:raise DataError('역 연결 결과 단지 누락: '+c['id'])
  walks=copy.deepcopy(row.get('walks',[]))
  for w in walks:
   if not w.get('name') or not w.get('lines') or not isinstance(w.get('distance_m'),int) or not 0<w['distance_m']<=1300 or not isinstance(w.get('minutes'),(int,float)) or not 0<w['minutes']<=20:raise DataError('역 보행거리·시간 조건 위반')
  c['station_walks']=[{k:v for k,v in w.items() if k!='route_nodes'} for w in walks]
  c['station_connection']={k:v for k,v in row.items() if k not in ('walks','lon','lat')}
  c['station_connection']['checked_at']=links['meta']['checked_at']
  if row.get('lon') is not None and row.get('lat') is not None:c.update(lon=row['lon'],lat=row['lat'])
  if walks:
   nearest=min(walks,key=lambda w:(w['distance_m'],w['name']))
   c.update(station=nearest['name'].removesuffix('역'),station_display=','.join(nearest['lines'])+nearest['name'].removesuffix('역'),station_walk_minutes=nearest['minutes'],station_distance_km=nearest['distance_m']/1000)
  else:
   c.update(station='',station_display='',station_walk_minutes=None,station_distance_km=None)
 out['meta']['transport']=links['meta'];validate_dataset(out);return out

def collect_sources(cache):
 client=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()));client.addheaders=[('User-Agent','kApt-personal-public-data/29')]
 page=client.open(PAGE,timeout=45).read().decode('utf-8')
 match=re.search(r'data: "kaptCode="\+kaptCode\+"&_csrf="\+"([^"]+)',page)
 if not match:raise DataError('공개 지도 조회 형식 변경')
 for code in ('11','41'):
  body=urllib.parse.urlencode({'bjdCode':code,'searchDate':last_closed_month().replace('-',''),'_csrf':match[1]}).encode()
  raw=client.open('https://www.k-apt.go.kr/kaptinfo/getKaptInfo_poi.do',body,timeout=60).read()
  if len(json.loads(raw).get('resultList',[]))<1000:raise DataError('공식 좌표 목록 급감')
  (cache/f'kapt-poi-{code}.json').write_bytes(raw)
 with urllib.request.urlopen(urllib.request.Request(PBF,headers={'User-Agent':'kApt-personal-public-data/29'}),timeout=120) as response,(cache/'south-korea.osm.pbf').open('wb') as dest:
  while True:
   chunk=response.read(1024*1024)
   if not chunk:break
   dest.write(chunk)
 if (cache/'south-korea.osm.pbf').stat().st_size<100000000:raise DataError('보행망 파일이 불완전함')
 # The extract's actual OSM timestamp is recorded from its PBF header, not guessed from wall-clock time.
 import osmium
 with osmium.io.Reader(str(cache/'south-korea.osm.pbf')) as reader:
  header=reader.header();stamp=header.get('osmosis_replication_timestamp') or header.get('timestamp')
 (cache/'source.json').write_text(json.dumps({'osm_date':stamp or 'PBF header timestamp unavailable'}))

def publish_transport(root,links):
 old=read_json(root/'data/site-data.json');d=apply_transport(old,links)
 previous_count=sum(bool(c.get('station_walks')) for c in old['complexes'])
 new_count=sum(bool(c.get('station_walks')) for c in d['complexes'])
 if previous_count and new_count<previous_count*.85:raise DataError('역 연결 단지 급감: 기존 자료 유지')
 prior=read_json(root/'data/site-data.previous.json')
 publish_bundle(root,d,previous=prior)
 # Metadata refresh clones this file; preserve links across the monthly sale/lease collection too.
 catalog=read_json(root/'data/complexes.json');byid={c['id']:c for c in d['complexes']}
 fields=['station','station_display','station_walks','station_walk_minutes','station_distance_km','station_connection','lon','lat']
 for c in catalog:
  if c['id'] in byid:
   for key in fields:c[key]=copy.deepcopy(byid[c['id']].get(key))
 atomic_json(root/'data/complexes.json',catalog)
 atomic_json(root/'data/transport-links.json',links)
 atomic_json(root/'reports/transport-report.json',{'status':'success','published':True,'finished_at':now(),**links['meta']})
 return new_count

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--cached-result',type=Path);ap.add_argument('--strict',action='store_true');args=ap.parse_args();root=Path(__file__).resolve().parents[1]
 try:
  if args.cached_result:links=json.loads(args.cached_result.read_text())
  else:
   with tempfile.TemporaryDirectory(prefix='k-apt-walk-') as temporary:
    cache=Path(temporary);collect_sources(cache)
    subprocess.run([sys.executable,str(root/'scripts/extract_walk_network.py'),str(cache/'south-korea.osm.pbf'),str(cache/'osm-walk-extract.json.gz')],check=True)
    subprocess.run([sys.executable,str(root/'scripts/build_transport_links.py'),str(root),str(cache)],check=True)
    links=json.loads((cache/'transport-links.json').read_text())
  count=publish_transport(root,links);print('역·노선 연결 발행:',count,'개 단지')
 except (OSError,ValueError,KeyError,TypeError,subprocess.CalledProcessError,DataError,RuntimeError,ImportError) as e:
  atomic_json(root/'reports/transport-report.json',{'status':'failed','published':False,'finished_at':now(),'error':str(e),'note':'기존 역 연결 자료를 유지합니다.'});print('역 연결 갱신 실패: 기존 자료 유지',file=sys.stderr)
  if args.strict:raise
if __name__=='__main__':main()
