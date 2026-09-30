#!/usr/bin/env python3
from pathlib import Path
import json, re

root=Path(__file__).resolve().parents[1]
index=root/"index.html"
data=root/"data"/"site-data.json"

obj=json.loads(data.read_text(encoding="utf-8"))
payload=json.dumps(obj,ensure_ascii=False,separators=(",",":"))
text=index.read_text(encoding="utf-8")
pat=r'window\.__EMBEDDED_DATA__=\{.*?\};</script>'
replacement='window.__EMBEDDED_DATA__='+payload+';</script>'
new,n=re.subn(pat,replacement,text,count=1,flags=re.S)
if n!=1:
    raise SystemExit("index.html의 __EMBEDDED_DATA__ 블록을 찾지 못했습니다.")
index.write_text(new,encoding="utf-8")
print("embedded",len(obj.get("complexes",[])),"complexes into",index)
