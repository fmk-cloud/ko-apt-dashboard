import sys,json,gzip,time
import osmium
start=time.time();pbf=sys.argv[1];destination=sys.argv[2];box=(126.65,36.9,127.4,37.78)
def inside(lon,lat):return box[0]<=lon<=box[2] and box[1]<=lat<=box[3]
class H(osmium.SimpleHandler):
 def __init__(self):super().__init__();self.poi=[];self.ways=[];self.rels=[]
 def node(self,n):
  if not n.location.valid() or not inside(n.location.lon,n.location.lat):return
  t=dict(n.tags)
  if t.get('railway') in ('station','halt','subway_entrance') or t.get('public_transport') in ('station','stop_position','platform'):
   self.poi.append({'id':n.id,'lon':n.location.lon,'lat':n.location.lat,'tags':t})
 def way(self,w):
  t=dict(w.tags);h=t.get('highway');foot=t.get('foot','');access=t.get('access','')
  if not h or foot in ('no','private') or access in ('no','private') and foot not in ('yes','designated','permissive'):return
  if h in ('motorway','motorway_link','trunk','trunk_link','construction','proposed','raceway') and foot not in ('yes','designated'):return
  if h not in ('footway','path','steps','pedestrian','living_street','residential','service','unclassified','road','tertiary','tertiary_link','secondary','secondary_link','primary','primary_link','cycleway','track','trunk','trunk_link'):return
  ns=[]
  for n in w.nodes:
   if not n.location.valid():return
   ns.append([n.ref,n.location.lon,n.location.lat])
  if not any(inside(n[1],n[2]) for n in ns):return
  self.ways.append({'id':w.id,'nodes':ns,'tags':{k:v for k,v in t.items() if k in ('highway','foot','access','name','bridge','tunnel','layer','sidewalk')}})
 def relation(self,r):
  t=dict(r.tags)
  if t.get('public_transport')=='stop_area' or t.get('route') in ('subway','light_rail','train','monorail'):
   self.rels.append({'id':r.id,'tags':t,'members':[[m.type,m.ref,m.role] for m in r.members]})
h=H();h.apply_file(pbf,locations=True,idx='flex_mem')
x={'box':box,'poi':h.poi,'ways':h.ways,'relations':h.rels}
with gzip.open(destination,'wt') as f:json.dump(x,f,ensure_ascii=False,separators=(',',':'))
print({'poi':len(h.poi),'ways':len(h.ways),'relations':len(h.rels),'seconds':round(time.time()-start,1)},flush=True)
for p in h.poi:
 if p['tags'].get('railway')=='station' and any(s in p['tags'].get('name:ko',p['tags'].get('name','')) for s in ('동탄','광나루','강변','당산')):print(p,flush=True)
