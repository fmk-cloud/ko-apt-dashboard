"""지역별 데이터 파일. 로컬 HTML에서도 동작하며 GitHub 웹 업로드 한도 이하로 저장."""
import collections,hashlib,json,os,re
from pathlib import Path
from pipeline import DataError,atomic_json,validate_dataset
from embed_data import embedded_html
PREFIX='window.__EMBEDDED_DATA__.complexes.push(...'
SUFFIX=');window.__DATA_PART_COUNT__=(window.__DATA_PART_COUNT__||0)+1;\n'
MARKER=r'<!-- REGIONAL_DATA_START -->.*?<!-- REGIONAL_DATA_END -->'
MAX_BYTES=8*1024*1024

def payload_json(obj):return json.dumps(obj,ensure_ascii=False,separators=(',',':'),allow_nan=False).replace('<','\\u003c').replace('\u2028','\\u2028').replace('\u2029','\\u2029')

def parse_part(text):
    if not text.startswith(PREFIX) or not text.endswith(SUFFIX):raise DataError('지역 데이터 파일 형식 오류')
    try:rows=json.loads(text[len(PREFIX):-len(SUFFIX)])
    except ValueError:raise DataError('지역 데이터 JSON 해석 실패') from None
    if not isinstance(rows,list):raise DataError('지역 데이터 배열 없음')
    return rows

def load_manifest(path,obj):
    base=Path(path).resolve().parent;cs=[]
    storage=obj['_storage']
    if storage.get('format')!='regional-js-v1':raise DataError('알 수 없는 데이터 저장 형식')
    seen=set()
    for part in storage['parts']:
        p=(base/part['file']).resolve()
        try:p.relative_to(base)
        except ValueError:raise DataError('지역 데이터 파일 경로 오류') from None
        if p in seen:raise DataError('지역 데이터 파일 중복')
        seen.add(p)
        try:b=p.read_bytes()
        except OSError:raise DataError('지역 데이터 파일 누락: '+part['file']) from None
        if hashlib.sha256(b).hexdigest()!=part['sha256']:raise DataError('지역 데이터 파일 검증값 불일치: '+part['file'])
        rows=parse_part(b.decode('utf-8'))
        if len(rows)!=part['count'] or any(c['region']!=part['region'] for c in rows):raise DataError('지역 데이터 범위/개수 불일치')
        cs.extend(rows)
    if len(cs)!=obj['meta']['complex_count']:raise DataError('전체 단지 개수 불일치')
    order=storage.get('complex_order')
    if order is not None:
        byid={c['id']:c for c in cs}
        if len(order)!=len(cs) or len(set(order))!=len(cs) or set(order)!=set(byid):raise DataError('단지 순서/식별자 불일치')
        cs=[byid[cid] for cid in order]
    result={'meta':obj['meta'],'complexes':cs};validate_dataset(result);return result

def prepare_bundle(data):
    validate_dataset(data);parts=[];files={};index=0
    by_region=collections.defaultdict(list)
    for c in data['complexes']:by_region[c['region']].append(c)
    for region in data['meta']['loaded_regions']:
        rows=by_region[region];pieces=[];size=len(PREFIX.encode())+len(SUFFIX.encode())+2
        def flush(pieces,index):
            text=PREFIX+'['+','.join(pieces)+']'+SUFFIX;h=hashlib.sha256(text.encode()).hexdigest();name=f'regions/region-{index:02}-{h[:12]}.js';files[name]=text;parts.append({'file':name,'sha256':h,'region':region,'count':len(pieces)})
        for c in rows:
            piece=payload_json(c);piece_size=len(piece.encode())+1
            if piece_size+len(PREFIX.encode())+len(SUFFIX.encode())+2>MAX_BYTES:raise DataError('단지 하나의 데이터가 파일 용량 한도를 초과')
            if pieces and size+piece_size>MAX_BYTES:
                flush(pieces,index);index+=1;pieces=[];size=len(PREFIX.encode())+len(SUFFIX.encode())+2
            pieces.append(piece);size+=piece_size
        if pieces:flush(pieces,index);index+=1
    if sum(p['count'] for p in parts)!=len(data['complexes']):raise DataError('지역 분할 결과 개수 불일치')
    meta=dict(data['meta']);meta['complex_count']=len(data['complexes'])
    return {'meta':meta,'_storage':{'format':'regional-js-v1','parts':parts,'complex_order':[c['id'] for c in data['complexes']]}},files

def regional_html(text,manifest):
    text=re.sub(MARKER,'',text,flags=re.S)
    result=embedded_html(text,{'meta':manifest['meta'],'complexes':[]})
    references=['<script>window.__DATA_PART_COUNT__=0;</script>']
    references += [f'<script src="data/{p["file"]}"></script>' for p in manifest['_storage']['parts']]
    count=len(manifest['_storage']['parts']);total=manifest['meta']['complex_count']
    order_json=payload_json(manifest['_storage']['complex_order'])
    references.append('<script>(()=>{const order=new Map('+order_json+'.map((id,i)=>[id,i]));const cs=window.__EMBEDDED_DATA__.complexes;if(window.__DATA_PART_COUNT__!=='+str(count)+'||cs.length!=='+str(total)+'||new Set(cs.map(c=>c.id)).size!=='+str(total)+'||cs.some(c=>!order.has(c.id))){window.__EMBEDDED_DATA__.complexes=[];Object.assign(window.__EMBEDDED_DATA__.meta,{source_verified:false,complex_count:0,far_verified_count:0,jeonse_rows:0,delivery_issue:"데이터 파일 일부를 읽지 못했습니다. data/regions 폴더까지 함께 업로드하거나 압축을 모두 풀고 다시 열어 주세요."});return;}cs.sort((a,b)=>order.get(a.id)-order.get(b.id));})();</script>')
    addition='\n<!-- REGIONAL_DATA_START -->\n'+'\n'.join(references)+'\n<!-- REGIONAL_DATA_END -->\n'
    return re.sub(r'(window\.__EMBEDDED_DATA__=\{.*?\};</script>)',lambda m:m[1]+addition,result,count=1,flags=re.S)

def publish_bundle(root,data,previous=None,html_source=None):
    root=Path(root);manifest,files=prepare_bundle(data);prior_manifest=None
    if previous is not None:
        prior_manifest,prior_files=prepare_bundle(previous);files.update(prior_files)
    html=regional_html(html_source if html_source is not None else (root/'index.html').read_text(encoding='utf-8'),manifest)
    # Content-addressed filenames preserve the live HTML's old references during preparation.
    for name,text in files.items():
        p=root/'data'/name;p.parent.mkdir(parents=True,exist_ok=True)
        if not p.exists() or p.read_bytes()!=text.encode('utf-8'):
            temp=p.with_suffix('.js.tmp');temp.write_text(text,encoding='utf-8');os.replace(temp,p)
    if prior_manifest is not None:atomic_json(root/'data/site-data.previous.json',prior_manifest)
    atomic_json(root/'data/site-data.json',manifest)
    temp=root/'index.html.tmp';temp.write_text(html,encoding='utf-8');os.replace(temp,root/'index.html')
    live={p['file'] for p in manifest['_storage']['parts']}
    if prior_manifest:live.update(p['file'] for p in prior_manifest['_storage']['parts'])
    for p in (root/'data/regions').glob('region-*.js'):
        if re.fullmatch(r'region-\d+-[a-f0-9]{12}\.js',p.name) and 'regions/'+p.name not in live:p.unlink()
    return manifest
