import sys,json,gzip,math,heapq,re,time,collections,hashlib
from pathlib import Path
from pyproj import Transformer
from shapely.geometry import LineString,Point
from shapely.strtree import STRtree
from pipeline import read_json,now
from transport_utils import norm,name,lines
start=time.time();root=Path(sys.argv[1]);cache=Path(sys.argv[2]);x=json.load(gzip.open(cache/'osm-walk-extract.json.gz','rt'))
proj=Transformer.from_crs('EPSG:4326','EPSG:5179',always_xy=True)
def xy(lon,lat):return proj.transform(lon,lat)
pois={p['id']:p for p in x['poi']};stationnodes={pid:p for pid,p in pois.items() if p['tags'].get('railway') in ('station','halt') and name(p['tags']) and not any(p['tags'].get(k) in ('yes','station','halt') for k in ('disused','abandoned','construction','proposed','disused:railway','construction:railway'))}
stationlines=collections.defaultdict(set)
for pid,p in stationnodes.items():stationlines[pid].update(lines(p['tags']))
# The exact station member and route relation establish its lines; station name proximity never establishes lines.
stopareas=[]
for r in x['relations']:
 t=r['tags'];ls=lines(t)
 if t.get('route') in ('subway','light_rail','train','monorail') and ls:
  for typ,pid,role in r['members']:
   if typ=='n' and pid in stationnodes:stationlines[pid].update(ls)
 if t.get('public_transport')=='stop_area':stopareas.append(r)
# stop_area may list stop positions instead of the railway=station node.
for r in stopareas:
 nm=name(r['tags']);members={i for typ,i,role in r['members'] if typ=='n'};matching=[pid for pid,p in stationnodes.items() if pid in members or name(p['tags'])==nm]
 ls=set().union(*(lines(pois[i]['tags']) for i in members if i in pois))
 for route in x['relations']:
  if route['tags'].get('route') not in ('subway','train','light_rail','monorail'):continue
  if any(typ=='n' and i in members for typ,i,role in route['members']):ls.update(lines(route['tags']))
 for pid in matching:stationlines[pid].update(ls)
# Not every national rail station is a commuter metro station. Keep only recognised present lines.
stations={}
for pid,p in stationnodes.items():
 ls=stationlines[pid]
 if not ls:continue
 nm=name(p['tags'])
 if not re.search('[가-힣]',nm):continue
 key=(nm,round(p['lon'],2),round(p['lat'],2))
 # Merge transfer station nodes within 600m under the same Korean name.
 key=next((k for k,v in stations.items() if v['name']==nm and math.hypot(xy(p['lon'],p['lat'])[0]-v['xy'][0],xy(p['lon'],p['lat'])[1]-v['xy'][1])<600),key)
 st=stations.setdefault(key,{'name':nm,'ids':[],'lines':set(),'lon':p['lon'],'lat':p['lat'],'xy':xy(p['lon'],p['lat']),'entrances':[]})
 st['ids'].append(pid);st['lines'].update(ls)
stations=list(stations.values());print('stations',len(stations),flush=True)
for st in stations:
 members=set()
 for r in stopareas:
  rs={i for typ,i,role in r['members'] if typ=='n'}
  if set(st['ids'])&rs or name(r['tags'])==st['name']:members|=rs
 entrances=[p for pid,p in pois.items() if pid in members and p['tags'].get('railway')=='subway_entrance']
 # Use unassigned entrance names only if they identify this exact station, never all nearby entrances.
 if not entrances:entrances=[p for p in pois.values() if p['tags'].get('railway')=='subway_entrance' and st['name'] in name(p['tags'])]
 st['entrances']=[{'id':p['id'],'lon':p['lon'],'lat':p['lat']} for p in entrances]
coords={};edges={}
for w in x['ways']:
 ns=w['nodes']
 for n in ns:coords[n[0]]=xy(n[1],n[2])
 for a,b in zip(ns,ns[1:]):
  if a[0]==b[0]:continue
  key=tuple(sorted((a[0],b[0])));length=math.dist(coords[a[0]],coords[b[0]])
  if length<=0 or length>5000:continue
  if key not in edges:edges[key]=length
x['ways']=[]
import gc;gc.collect()
adj=collections.defaultdict(list)
segments=[];edgepairs=[]
for (a,b),length in edges.items():
 adj[a].append((b,length));adj[b].append((a,length));segments.append(LineString([coords[a],coords[b]]));edgepairs.append((a,b,length))
tree=STRtree(segments);print('graph',len(coords),len(edges),'seconds',round(time.time()-start,1),flush=True)
def snap(point,limit=150):
 pt=Point(point);idx=int(tree.nearest(pt));line=segments[idx];d=pt.distance(line)
 if d>limit:return None
 a,b,length=edgepairs[idx];offset=line.project(pt)
 return {'starts':[(a,d+offset),(b,d+length-offset)],'connector':d,'edge':(a,b),'offset':offset,'length':length}
# Subway entrances are endpoints. A centre is used only where no matching entrance is mapped and is explicitly marked.
ends=collections.defaultdict(list)
for i,st in enumerate(stations):
 points=st['entrances'] or [{'id':pid,'lon':stationnodes[pid]['lon'],'lat':stationnodes[pid]['lat']} for pid in st['ids']]
 st['usable_endpoints']=0
 for p in points:
  sn=snap(xy(p['lon'],p['lat']),80)
  if not sn:continue
  st['usable_endpoints']+=1
  for n,d in sn['starts']:ends[n].append((i,d,p['id'],sn['connector']))
meta=read_json(root/'data/site-data.json');rows=json.load(open(cache/'kapt-poi-11.json'))['resultList']+json.load(open(cache/'kapt-poi-41.json'))['resultList'];byid={r['kaptCode']:r for r in rows}
kproj=Transformer.from_crs('+proj=tmerc +lat_0=38 +lon_0=127.0028902777778 +k=1 +x_0=200000 +y_0=500000 +ellps=bessel +units=m +no_defs +towgs84=-115.80,474.99,674.11,1.16,-2.31,-1.63,6.43','EPSG:4326',always_xy=True)
links={};status=collections.Counter()
for c in meta['complexes']:
 r=byid.get(c['id']);pos=None;source=''
 if r and r.get('xCoord') is not None and r.get('yCoord') is not None:
  lon,lat=kproj.transform(r['xCoord'],r['yCoord']);source='K-apt getKaptInfo_poi'
  if 126.6<lon<127.5 and 36.8<lat<37.85:pos=xy(lon,lat)
 if not pos and c.get('lat') and c.get('lon'):
  lon,lat=c['lon'],c['lat'];pos=xy(lon,lat);source='existing coordinate'
 if not pos:links[c['id']]={'status':'coordinate_unconfirmed','walks':[]};status['coordinate_unconfirmed']+=1;continue
 sn=snap(pos)
 if not sn:links[c['id']]={'status':'walk_network_unconnected','lon':lon,'lat':lat,'coordinate_source':source,'walks':[]};status['walk_network_unconnected']+=1;continue
 best={n:d for n,d in sn['starts']};heap=[(d,n) for n,d in sn['starts']];heapq.heapify(heap);hits={};prev={}
 while heap:
  d,n=heapq.heappop(heap)
  if d>1300:break
  if d!=best.get(n):continue
  for si,tail,eid,connector in ends.get(n,[]):
   total=d+tail
   if total>1300:continue
   if si not in hits or total<hits[si][0]:hits[si]=(total,n,eid,connector)
  for m,weight in adj[n]:
   nd=d+weight
   if nd<=1300 and nd<best.get(m,float('inf')):best[m]=nd;prev[m]=n;heapq.heappush(heap,(nd,m))
 walks=[]
 for si,(dist,n,eid,connector) in hits.items():
  st=stations[si];path=[];v=n
  while v in prev:path.append(v);v=prev[v]
  path.append(v)
  walks.append({'name':st['name']+'역','lines':sorted(st['lines'],key=lambda x:(not x.isdigit(),int(x) if x.isdigit() else x)),'distance_m':math.ceil(dist),'minutes':round(dist/65,1),'method':'osm_walk_network_estimate','endpoint':'entrance' if st['entrances'] else 'station_point','station_osm_ids':st['ids'],'endpoint_osm_id':eid,'start_connector_m':round(sn['connector'],1),'end_connector_m':round(connector,1),'route_nodes':path[::-1]})
 # Duplicate station records may occur at rounding boundaries; choose shortest per Korean name.
 dedup={}
 for w in walks:
  if w['name'] not in dedup or w['distance_m']<dedup[w['name']]['distance_m']:dedup[w['name']]=w
 walks=sorted(dedup.values(),key=lambda w:(w['distance_m'],w['name']))
 # Rounding up distance means an included row is never displayed as <=1300 if the real value exceeds the boundary.
 walks=[w for w in walks if w['distance_m']<=1300]
 key='linked' if walks else 'no_reachable_station_within_1300m';status[key]+=1
 links[c['id']]={'status':key,'lon':lon,'lat':lat,'coordinate_source':source,'walks':walks}
 if c['name'] in ['당산푸르지오','광장현대5단지','동탄역 롯데캐슬 아파트']:print(c['name'],[{k:v for k,v in w.items() if k!='route_nodes'} for w in walks],flush=True)
 if len(links)%250==0:print('processed',len(links),dict(status),flush=True)
result={'meta':{'checked_at':now(),'osm_date':json.loads((cache/'source.json').read_text()).get('osm_date','source header unavailable'),'distance_limit_m':1300,'walking_speed_m_per_min':65,'method':'K-apt coordinates + OSM pedestrian shortest path','origin':'단지 지도 좌표','not_measured_from_verified_gate':True,'licence':'Open Database License 1.0 / © OpenStreetMap contributors','source':'https://download.geofabrik.de/asia/south-korea.html','source_pbf_sha256':hashlib.sha256((cache/'south-korea.osm.pbf').read_bytes()).hexdigest(),'summary':dict(status),'graph_nodes':len(coords),'graph_edges':len(edges),'stations':len(stations)},'complexes':links,'stations':[{k:(sorted(v) if isinstance(v,set) else v) for k,v in st.items() if k!='xy'} for st in stations]}
(cache/'transport-links.json').write_text(json.dumps(result,ensure_ascii=False,separators=(',',':')))
print('done',dict(status),'seconds',round(time.time()-start,1),flush=True)
