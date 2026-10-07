"""역 이름/노선 정규화. 역명(김포공항 등)을 노선으로 오인하지 않는다."""
import re
def norm(s):return re.sub(r'\([^)]*\)|\s|역$','',s)

def name(t):return norm(t.get('name:ko',t.get('name','')))

def lines(t):
 s=' '.join(str(t.get(k,'')) for k in ('name:ko','name','ref','line','network','operator','route'))
 found=set()
 for n in re.findall(r'(?<![0-9])([1-9])\s*(?:호선|Line)|(?:Line|LINE)\s*([1-9])(?![0-9])',s):found.add(next(v for v in n if v))
 if t.get('route')=='subway' and re.fullmatch('[1-9]',t.get('ref','')):found.add(t['ref'])
 for token,label in [('신분당','신분당'),('Shinbundang','신분당'),('수인','수인분당'),('Suin','수인분당'),('분당','수인분당'),('Bundang','수인분당'),('경의','경의중앙'),('중앙선','경의중앙'),('Gyeongui','경의중앙'),('공항철도','공항'),('AREX','공항'),('Airport Railroad','공항'),('Airport Railway','공항'),('경춘','경춘'),('Gyeongchun','경춘'),('서해','서해'),('Seo hae','서해'),('신림선','신림'),('Sillim Line','신림'),('우이신설','우이신설'),('Ui-Sinseol','우이신설'),('GTX-A','GTX-A'),('GTX A','GTX-A'),('SRT','SRT')]:
  if token in s:found.add(label)
 # Shinbundang contains Bundang; discard the spurious prefix-derived line.
 if '신분당' in found and not re.search(r'수인|(?<!신)분당|(?<!Shin)Bundang',s):found.discard('수인분당')
 return found

