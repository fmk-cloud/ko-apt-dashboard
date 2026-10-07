import json,re
from pathlib import Path
from pipeline import validate_dataset,read_json
root=Path(__file__).resolve().parents[1]
d=read_json(root/'data/site-data.json')
validate_dataset(d)
s=(root/'index.html').read_text()
m=re.search(r'window\.__EMBEDDED_DATA__=(\{.*?\});</script>',s,re.S)
assert m, 'HTML 데이터 블록 누락'
manifest=json.loads((root/'data/site-data.json').read_text())
if '_storage' in manifest:
    assert json.loads(m[1])=={'meta':d['meta'],'complexes':[]}, 'HTML 데이터 메타 불일치'
    for part in manifest['_storage']['parts']:assert 'src="data/'+part['file']+'"' in s, '지역 데이터 스크립트 누락'
else:assert json.loads(m[1])==d, 'HTML 내장 데이터 불일치'
assert d['meta']['source_verified'] and d['meta']['provider'] in ('seoul_public','seoul_gyeonggi_official')
assert 'id="loadFilterBtn">복구</button>' in s
assert 'paintUnsupportedPopover(type)' in s
if d['meta'].get('features',{}).get('gap'):
    cs=d['complexes']
    assert d['meta']['jeonse_rows']==sum(len(c.get('jeonse_tx',[])) for c in cs), '전세 행 수 불일치'
    assert d['meta']['far_verified_count']==sum((c.get('far_info') or {}).get('status')=='verified' for c in cs), '용적률 개수 불일치'
    for c in cs:
        f=c.get('far_info') or {}
        if f.get('status')=='verified':assert c['far']==f['value'] and 0<c['far']<=2000
        else:assert c.get('far') is None, '미확인 용적률을 숫자로 노출'
        for t in c.get('jeonse_tx',[]):
            assert len(t)==7 and d['meta']['jeonse_from']<=t[0][:7]<=d['meta']['jeonse_to']
            assert 0<t[1]<2000 and isinstance(t[3],int) and t[3]>0
            assert t[2] is None or isinstance(t[2],int) and -10<=t[2]<=200
print('검증 완료:',len(d['complexes']),'개 단지')
