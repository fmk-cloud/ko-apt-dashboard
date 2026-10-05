import json,re
from pathlib import Path
from pipeline import validate_dataset
root=Path(__file__).resolve().parents[1]
d=json.loads((root/'data/site-data.json').read_text())
validate_dataset(d)
s=(root/'index.html').read_text()
m=re.search(r'window\.__EMBEDDED_DATA__=(\{.*?\});</script>',s,re.S)
assert m and json.loads(m[1])==d, 'HTML 내장 데이터 불일치'
assert d['meta']['source_verified'] and d['meta']['provider']=='seoul_public'
assert 'id="loadFilterBtn">복구</button>' in s
assert 'paintUnsupportedPopover(type)' in s
print('검증 완료:',len(d['complexes']),'개 단지')
