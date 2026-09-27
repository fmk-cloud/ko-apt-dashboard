#!/usr/bin/env python3
"""Build static apartment comparison data for Yeongdeungpo, Seongdong and Mapo.

The output is data/site-data.json consumed directly by assets/app.js.
No server/database is required after the JSON is built.

Sources
- apartment metadata: cached public Seoul apartment metadata CSV generated from Seoul OA-15818
- apartment trades: MOLIT apartment trade API (official key) or a hosted proxy over MOLIT data
- FAR (optional): hosted building-register proxy, cached in data/far-cache.json
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import difflib
import io
import json
import os
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
OUT = DATA_DIR / "site-data.json"
FAR_CACHE = DATA_DIR / "far-cache.json"

DISTRICTS = {
    "영등포구": "11560",
    "성동구": "11200",
    "마포구": "11440",
}

# This CSV is generated from Seoul Open Data OA-15818 by the public wmjoo/seoul_apt project.
# It is used only as a cache of public metadata; the source dataset remains Seoul Open Data.
META_URL = "https://raw.githubusercontent.com/wmjoo/seoul_apt/main/seoul_apartments_metadata.csv"
PROXY_BASE = os.environ.get("KSKILL_PROXY_BASE_URL", "https://k-skill-proxy.nomadamas.org").rstrip("/")
MOLIT_URL = "https://apis.data.go.kr/1613000/RTMSDataSvcAptTradeDev/getRTMSDataSvcAptTradeDev"

STATION_LINES = {
    # Yeongdeungpo
    "당산":"2,9", "영등포구청":"2,5", "문래":"2", "영등포":"1", "신길":"1,5",
    "대림":"2,7", "도림천":"2", "양평":"5", "여의도":"5,9", "여의나루":"5",
    "샛강":"9,신림", "국회의사당":"9", "영등포시장":"5", "보라매":"7,신림",
    "신풍":"7", "신대방삼거리":"7",
    # Seongdong
    "왕십리":"2,5,경의중앙,수인분당", "서울숲":"수인분당", "성수":"2", "뚝섬":"2",
    "옥수":"3,경의중앙", "금호":"3", "신금호":"5", "행당":"5", "마장":"5",
    "상왕십리":"2", "응봉":"경의중앙", "한양대":"2", "용답":"2", "신답":"2",
    # Mapo
    "공덕":"5,6,경의중앙,공항", "마포":"5", "대흥":"6", "광흥창":"6", "상수":"6",
    "합정":"2,6", "홍대입구":"2,경의중앙,공항", "애오개":"5", "아현":"2", "신촌":"2",
    "이대":"2", "서강대":"경의중앙", "망원":"6", "월드컵경기장":"6", "마포구청":"6",
    "디지털미디어시티":"6,경의중앙,공항", "가좌":"경의중앙",
}

UA = "ko-apt-dashboard/1.0 (+personal static analytics)"


def request_bytes(url: str, timeout: int = 45, tries: int = 4) -> bytes:
    last = None
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except Exception as exc:  # noqa: BLE001
            last = exc
            if attempt + 1 < tries:
                time.sleep(1.2 * (attempt + 1))
    raise RuntimeError(f"request failed: {url}: {last}")


def get_json(url: str, timeout: int = 45) -> dict[str, Any]:
    return json.loads(request_bytes(url, timeout=timeout).decode("utf-8"))


def clean_text(v: Any) -> str:
    return "" if v is None else str(v).strip()


def first_value(row: dict[str, Any], candidates: Iterable[str]) -> str:
    for key in candidates:
        v = row.get(key)
        if v is not None and str(v).strip() not in ("", "nan", "None"):
            return str(v).strip()
    return ""


def to_number(v: Any) -> float | None:
    if v is None:
        return None
    s = str(v).strip().replace(",", "").replace("%", "")
    if not s or s.lower() in {"nan", "none", "null"}:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def to_int(v: Any) -> int | None:
    n = to_number(v)
    return int(round(n)) if n is not None else None


def norm_name(s: str) -> str:
    s = unicodedata.normalize("NFKC", s or "").lower()
    s = re.sub(r"\([^)]*\)", "", s)
    s = s.replace("아파트", "").replace("apt", "")
    s = re.sub(r"[^0-9a-z가-힣]", "", s)
    return s


def norm_station(s: str) -> str:
    s = clean_text(s).replace("역", "").strip()
    return s


def station_display(station: str) -> str:
    st = norm_station(station)
    if not st:
        return ""
    lines = STATION_LINES.get(st)
    return f"{lines}{st}" if lines else st


def format_completed(row: dict[str, Any]) -> str | None:
    raw = first_value(row, ["준공일자", "사용승인일", "원본_USE_APRV_YMD", "USE_APRV_YMD"])
    if raw:
        digits = re.sub(r"\D", "", raw)
        if len(digits) >= 6:
            return f"{digits[:4]}.{digits[4:6]}"
        if len(digits) >= 4:
            return digits[:4]
    year = first_value(row, ["건축연도", "build_year", "BUILD_YEAR"])
    m = re.search(r"(19|20)\d{2}", year)
    return m.group(0) if m else None


def district_from_row(row: dict[str, Any]) -> str:
    raw = first_value(row, ["자치구", "SGG_ADDR", "원본_SGG_ADDR", "SGG_NM"])
    for d in DISTRICTS:
        if d in raw:
            return d
    return raw


def load_metadata() -> list[dict[str, Any]]:
    print("[meta] downloading Seoul apartment metadata cache…")
    raw = request_bytes(META_URL, timeout=60)
    text = raw.decode("utf-8-sig", errors="replace")
    rows = list(csv.DictReader(io.StringIO(text)))
    result: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for row in rows:
        region = district_from_row(row)
        if region not in DISTRICTS:
            continue
        name = first_value(row, ["아파트명", "APT_NM", "원본_APT_NM"])
        if not name:
            continue
        address = first_value(row, ["주소", "APT_RDN_ADDR", "원본_APT_RDN_ADDR", "원본_APT_STDG_ADDR"])
        households = to_int(first_value(row, ["세대수", "TNOHSH", "원본_TNOHSH", "TOT_HSHLD_CO"]));
        completed = format_completed(row)
        station = norm_station(first_value(row, ["가장가까운지하철역", "nearest_station", "지하철역"]));
        far = None
        for key, value in row.items():
            kl = (key or "").lower().replace("_", "")
            if "용적률" in (key or "") or kl in {"vlrat", "volumerate", "floorarearatio"}:
                far = to_number(value)
                if far is not None:
                    break
        build_year = to_int(first_value(row, ["건축연도", "build_year"]))
        key = (region, norm_name(name), address)
        if key in seen:
            continue
        seen.add(key)
        result.append({
            "id": first_value(row, ["원본_APT_CD", "APT_CD", "단지코드"]) or f"{DISTRICTS[region]}-{len(result)+1}",
            "region": region,
            "name": name,
            "address": address,
            "households": households,
            "completed": completed,
            "build_year": build_year or (int(completed[:4]) if completed and completed[:4].isdigit() else None),
            "station": station,
            "station_display": station_display(station),
            "station_distance_km": to_number(first_value(row, ["지하철역거리_km", "station_distance_km"])),
            "lat": to_number(first_value(row, ["위도", "LAT", "Y"])),
            "lon": to_number(first_value(row, ["경도", "LNG", "LON", "X"])),
            "far": far,
            "naver": "https://new.land.naver.com/search?" + urllib.parse.urlencode({"sk": name}),
            "tx": [],
        })
    print(f"[meta] loaded {len(result)} complexes in 3 districts")
    return result


def month_range(start_ym: str, end_ym: str) -> list[str]:
    y,m = int(start_ym[:4]), int(start_ym[5:] if "-" in start_ym else start_ym[4:])
    ey,em = int(end_ym[:4]), int(end_ym[5:] if "-" in end_ym else end_ym[4:])
    out=[]
    while (y,m) <= (ey,em):
        out.append(f"{y:04d}{m:02d}")
        m += 1
        if m > 12: y,m = y+1,1
    return out


def current_ym() -> str:
    now = dt.datetime.now(dt.timezone(dt.timedelta(hours=9)))
    return f"{now.year:04d}{now.month:02d}"


def xml_text(item: ET.Element, names: list[str]) -> str:
    for name in names:
        el=item.find(name)
        if el is not None and el.text and el.text.strip():
            return el.text.strip()
    return ""


def fetch_trades_official(lawd: str, ymd: str, key: str) -> list[dict[str, Any]]:
    params={"serviceKey":urllib.parse.unquote(key),"LAWD_CD":lawd,"DEAL_YMD":ymd,"numOfRows":"1000","pageNo":"1"}
    url=MOLIT_URL+"?"+urllib.parse.urlencode(params, safe="%")
    raw=request_bytes(url,timeout=60)
    root=ET.fromstring(raw)
    result_code=(root.findtext(".//resultCode") or "").strip()
    if result_code and result_code not in {"000","00"}:
        raise RuntimeError(f"MOLIT resultCode {result_code}: {(root.findtext('.//resultMsg') or '').strip()}")
    out=[]
    for item in root.findall(".//item"):
        deal_type=xml_text(item,["dealingGbn","거래유형"])
        cancel=xml_text(item,["cdealType","해제여부"])
        if "직거래" in deal_type or cancel not in {"", "0", "해제아님"}:
            continue
        name=xml_text(item,["aptNm","아파트"]); area=to_number(xml_text(item,["excluUseAr","전용면적"])); floor=to_int(xml_text(item,["floor","층"])); price=to_int(xml_text(item,["dealAmount","거래금액"]));
        yy=to_int(xml_text(item,["dealYear","년"])); mm=to_int(xml_text(item,["dealMonth","월"])); dd=to_int(xml_text(item,["dealDay","일"]));
        if not (name and area and floor is not None and price and yy and mm and dd):
            continue
        out.append({"name":name,"district":xml_text(item,["umdNm","법정동"]),"area_m2":area,"floor":floor,"price_10k":price,"deal_date":f"{yy:04d}-{mm:02d}-{dd:02d}","build_year":to_int(xml_text(item,["buildYear","건축년도"])),"deal_type":deal_type})
    return out


def fetch_trades_proxy(lawd: str, ymd: str) -> list[dict[str, Any]]:
    q=urllib.parse.urlencode({"lawd_cd":lawd,"deal_ymd":ymd,"num_of_rows":1000})
    data=get_json(f"{PROXY_BASE}/v1/real-estate/apartment/trade?{q}",timeout=60)
    return data.get("items") or []


def fetch_trades(lawd: str, ymd: str) -> list[dict[str, Any]]:
    key=os.environ.get("PUBLIC_DATA_API_KEY") or os.environ.get("MOLIT_API_KEY") or ""
    if key:
        try:
            return fetch_trades_official(lawd,ymd,key)
        except Exception as exc:  # noqa: BLE001
            print(f"[trade] official API failed, proxy fallback: {exc}",file=sys.stderr)
    return fetch_trades_proxy(lawd,ymd)


def candidate_score(meta: dict[str, Any], trade: dict[str, Any]) -> float:
    a,b=norm_name(meta["name"]),norm_name(clean_text(trade.get("name")))
    if not a or not b: return 0
    if a==b: score=1.0
    elif a in b or b in a: score=.92
    else: score=difflib.SequenceMatcher(None,a,b).ratio()
    by=trade.get("build_year")
    if by and meta.get("build_year"):
        diff=abs(int(by)-int(meta["build_year"]))
        if diff==0: score+=.05
        elif diff<=2: score+=.02
        elif diff>=7: score-=.12
    return score


def build_matcher(complexes: list[dict[str, Any]]) -> dict[str, Any]:
    by_region=defaultdict(list); exact=defaultdict(dict)
    for c in complexes:
        by_region[c["region"]].append(c)
        exact[c["region"]].setdefault(norm_name(c["name"]),[]).append(c)
    return {"by_region":by_region,"exact":exact}


def match_complex(matcher: dict[str, Any], region: str, trade: dict[str, Any]) -> dict[str, Any] | None:
    key=norm_name(clean_text(trade.get("name")))
    ex=matcher["exact"][region].get(key,[])
    if len(ex)==1:return ex[0]
    pool=ex or matcher["by_region"][region]
    scored=sorted(((candidate_score(c,trade),c) for c in pool),key=lambda x:x[0],reverse=True)
    if not scored:return None
    threshold=.75 if ex else .79
    return scored[0][1] if scored[0][0]>=threshold else None


def trade_tuple(t: dict[str, Any]) -> list[Any] | None:
    name=clean_text(t.get("name")); area=to_number(t.get("area_m2")); floor=to_int(t.get("floor")); price=to_int(t.get("price_10k")); date=clean_text(t.get("deal_date")); deal_type=clean_text(t.get("deal_type"))
    if not (name and area and floor is not None and price and re.match(r"\d{4}-\d{2}-\d{2}",date)):
        return None
    if floor < 10 or "직거래" in deal_type:
        return None
    if not (57 <= area <= 61.5 or 82 <= area <= 86.5):
        return None
    return [date,round(area,2),floor,price]


def load_far_cache() -> dict[str, Any]:
    if FAR_CACHE.exists():
        try:return json.loads(FAR_CACHE.read_text(encoding="utf-8"))
        except Exception:return {}
    return {}


def save_far_cache(cache: dict[str, Any]) -> None:
    FAR_CACHE.write_text(json.dumps(cache,ensure_ascii=False,indent=2),encoding="utf-8")


def deep_find_far(obj: Any) -> float | None:
    if isinstance(obj,dict):
        for k,v in obj.items():
            nk=re.sub(r"[^a-z]","",str(k).lower())
            if nk in {"vlrat","volumerate","floorarearatio"} or "용적률" in str(k):
                n=to_number(v)
                if n is not None and 1 <= n <= 2000:return n
        for v in obj.values():
            n=deep_find_far(v)
            if n is not None:return n
    elif isinstance(obj,list):
        for v in obj:
            n=deep_find_far(v)
            if n is not None:return n
    return None


def geocode_pnu(address: str) -> str | None:
    if not address:return None
    url=f"{PROXY_BASE}/v1/kakao-local/geocode?"+urllib.parse.urlencode({"q":address,"limit":2})
    data=get_json(url,timeout=25)
    docs=data.get("documents") or data.get("results") or []
    if not docs:return None
    doc=docs[0]
    addr=doc.get("address") if isinstance(doc.get("address"),dict) else doc
    b=clean_text(addr.get("b_code")); main=clean_text(addr.get("main_address_no")); sub=clean_text(addr.get("sub_address_no")) or "0"; mountain=str(addr.get("mountain_yn",'N')).upper() in {'Y','1','TRUE'}
    if len(b)!=10 or not main.isdigit():return None
    return f"{b}{'2' if mountain else '1'}{int(main):04d}{int(sub or 0):04d}"


def lookup_far(address: str) -> float | None:
    pnu=geocode_pnu(address)
    if not pnu:return None
    url=f"{PROXY_BASE}/v1/building-register/title?"+urllib.parse.urlencode({"pnu":pnu,"numOfRows":100})
    return deep_find_far(get_json(url,timeout=30))


def enrich_far(complexes: list[dict[str, Any]], enabled: bool) -> None:
    cache=load_far_cache(); changed=False
    targets=[c for c in complexes if (c.get("households") or 0)>=300]
    for i,c in enumerate(targets,1):
        ck=f"{c['region']}|{c['name']}|{c.get('address','')}"
        if c.get("far") is not None:
            cache[ck]=c["far"]
        elif ck in cache:
            c["far"]=cache[ck]
        elif enabled:
            try:
                c["far"]=lookup_far(c.get("address") or "")
            except Exception as exc:  # noqa: BLE001
                print(f"[far] {c['name']}: {exc}",file=sys.stderr);c["far"]=None
            cache[ck]=c["far"];changed=True
            if i%20==0: print(f"[far] {i}/{len(targets)}")
            time.sleep(.08)
    if changed or not FAR_CACHE.exists():save_far_cache(cache)


def existing_transactions() -> dict[str,list[list[Any]]]:
    if not OUT.exists():return {}
    try:
        d=json.loads(OUT.read_text(encoding="utf-8"));return {str(c.get("id")):c.get("tx",[]) for c in d.get("complexes",[])}
    except Exception:return {}


def build(mode: str, start: str, enrich_far_flag: bool) -> None:
    DATA_DIR.mkdir(parents=True,exist_ok=True)
    complexes=load_metadata();matcher=build_matcher(complexes)
    oldtx=existing_transactions() if mode=="incremental" else {}
    for c in complexes:
        if str(c["id"]) in oldtx:c["tx"]=oldtx[str(c["id"])]

    end=current_ym();
    if mode=="incremental":
        ey,em=int(end[:4]),int(end[4:]); d=dt.date(ey,em,1); d=(d-dt.timedelta(days=95)).replace(day=1); fetch_start=f"{d.year:04d}{d.month:02d}"
        refresh_months=set(month_range(fetch_start,end))
        for c in complexes:c["tx"]=[x for x in c["tx"] if x[0][:7].replace('-','') not in refresh_months]
    else:
        fetch_start=start.replace('-','')

    months=month_range(fetch_start,end);total=len(months)*len(DISTRICTS);done=0;unmatched=Counter()
    for region,lawd in DISTRICTS.items():
        for ym in months:
            done+=1;print(f"[trade] {done}/{total} {region} {ym}")
            try:items=fetch_trades(lawd,ym)
            except Exception as exc:
                raise RuntimeError(f"trade fetch failed {region} {ym}: {exc}") from exc
            for t in items:
                tup=trade_tuple(t)
                if tup is None:continue
                c=match_complex(matcher,region,t)
                if c is None:
                    unmatched[(region,clean_text(t.get('name')))] += 1;continue
                c["tx"].append(tup)
            time.sleep(.05)

    # de-duplicate and sort
    for c in complexes:
        seen=set(); tx=[]
        for x in sorted(c["tx"],key=lambda z:(z[0],z[1],z[2],z[3])):
            k=tuple(x)
            if k not in seen:seen.add(k);tx.append(x)
        c["tx"]=tx

    enrich_far(complexes,enrich_far_flag)
    current=f"{end[:4]}-{end[4:]}"; min_month=start if '-' in start else f"{start[:4]}-{start[4:]}"
    now=dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).strftime("%Y-%m-%d %H:%M KST")
    payload={
        "meta":{
            "status":"full",
            "updated_at":now,
            "current_month":current,
            "min_month":min_month,
            "loaded_regions":list(DISTRICTS.keys()),
            "complex_count":len(complexes),
            "note":"영등포구·성동구·마포구 전체 단지 기본정보와 59/84㎡ 중층 실거래를 수록했습니다.",
            "sources":{
                "trades":"국토교통부 아파트 매매 실거래가",
                "metadata":"서울 열린데이터광장 OA-15818 기반 공개 메타데이터 캐시",
                "far":"건축물대장 표제부(매칭 가능한 단지에 한함)"
            }
        },
        "complexes":complexes,
    }
    OUT.write_text(json.dumps(payload,ensure_ascii=False,separators=(',',':')),encoding="utf-8")
    print(f"[done] wrote {OUT} ({OUT.stat().st_size/1024/1024:.2f} MB), complexes={len(complexes)}, unmatched={sum(unmatched.values())}")
    if unmatched:
        print("[match] most common unmatched:")
        for (r,nm),cnt in unmatched.most_common(20):print(f"  {r} {nm}: {cnt}")


def main() -> None:
    ap=argparse.ArgumentParser()
    ap.add_argument("--mode",choices=["full","incremental"],default="incremental")
    ap.add_argument("--start",default="2022-09",help="full build start month YYYY-MM")
    ap.add_argument("--enrich-far",action="store_true",help="query building-register proxy for missing FAR (cached)")
    args=ap.parse_args()
    build(args.mode,args.start,args.enrich_far)

if __name__=="__main__":main()
