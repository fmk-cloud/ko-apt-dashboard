#!/usr/bin/env python3
import json,re,os
from pathlib import Path

def embedded_html(text,obj):
 # Escape '<' so data names cannot terminate the script element.
 payload=json.dumps(obj,ensure_ascii=False,separators=(',',':')).replace('<','\\u003c').replace('\u2028','\\u2028').replace('\u2029','\\u2029')
 pattern=r'window\.__EMBEDDED_DATA__=\{.*?\};</script>'
 if len(re.findall(pattern,text,flags=re.S))!=1:raise ValueError('내장 데이터 블록이 정확히 하나 있어야 합니다.')
 result,n=re.subn(pattern,lambda _: 'window.__EMBEDDED_DATA__='+payload+';</script>',text,count=1,flags=re.S)
 if n!=1:raise ValueError('내장 데이터 블록이 정확히 하나 있어야 합니다.')
 return result

def main():
 root=Path(__file__).resolve().parents[1];index=root/'index.html'
 text=embedded_html(index.read_text(encoding='utf-8'),json.loads((root/'data/site-data.json').read_text(encoding='utf-8')))
 temp=index.with_suffix('.html.tmp');temp.write_text(text,encoding='utf-8');os.replace(temp,index)
 print('내장 데이터 갱신 완료')
if __name__=='__main__':main()
