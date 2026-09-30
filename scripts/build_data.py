#!/usr/bin/env python3
"""
성동구·마포구·동작구·영등포구 4개구의 아파트 매매·전세 실거래를 수집해
ko-apt UI용 site-data.json을 만든다.

가격 비교 규칙은 브라우저(app.js)에서 수행:
- 전용 59/84 대표타입 우선
- 1~9층 제외
- 수집기간 내 단지의 관측 최고층 제외
- 시작월 거래 없음 -> 이후 첫 거래월
- 종료월 거래 없음 -> 이전 최근 거래월
- 선택된 월에서는 가장 높은 실거래 1건을 기준가격으로 사용

환경변수:
  PUBLIC_DATA_API_KEY 또는 MOLIT_API_KEY
선택:
  KAPT_API_KEY (없으면 PUBLIC_DATA_API_KEY 재사용 시도; 서울/경기 세대수·사용승인일 보강)
"""
from __future__ import annotations

import argparse
import difflib
import datetime as dt
import json
import os
import re
import sys
import time
import unicodedata
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path
from typing import Any

OUT_DEFAULT = Path("data/site-data.json")
MOLIT_URL = "https://apis.data.go.kr/1613000/RTMSDataSvcAptTradeDev/getRTMSDataSvcAptTradeDev"
MOLIT_RENT_URL = "https://apis.data.go.kr/1613000/RTMSDataSvcAptRent/getRTMSDataSvcAptRent"
KAPT_LIST_URL = "https://apis.data.go.kr/1613000/AptListService3/getSidoAptList3"
KAPT_BASIC_URL = "https://apis.data.go.kr/1613000/AptBasisInfoServiceV4/getAphusBassInfoV4"
BLD_RECAP_URL = "https://apis.data.go.kr/1613000/BldRgstHubService/getBrRecapTitleInfo"
BLD_TITLE_URL = "https://apis.data.go.kr/1613000/BldRgstHubService/getBrTitleInfo"
UA = "ko-apt-dashboard-simple/2.0"

SEOUL = {
    "종로구":"11110","중구":"11140","용산구":"11170","성동구":"11200","광진구":"11215",
    "동대문구":"11230","중랑구":"11260","성북구":"11290","강북구":"11305","도봉구":"11320",
    "노원구":"11350","은평구":"11380","서대문구":"11410","마포구":"11440","양천구":"11470",
    "강서구":"11500","구로구":"11530","금천구":"11545","영등포구":"11560","동작구":"11590",
    "관악구":"11620","서초구":"11650","강남구":"11680","송파구":"11710","강동구":"11740",
}

# API 호출은 행정구 단위로 하고, UI에서는 아래 생활권 태그를 붙인다.
GYEONGGI_ADMIN = {
    "과천시":"41290",
    "성남시 수정구":"41131",
    "성남시 중원구":"41133",
    "성남시 분당구":"41135",
    "광명시":"41210",
    "하남시":"41450",
    "안양시 동안구":"41173",
    "용인시 수지구":"41465",
    "수원시 영통구":"41117",
    "화성시":"41590",
    "고양시 덕양구":"41281",
    "고양시 일산동구":"41285",
    "고양시 일산서구":"41287",
    "의왕시":"41430",
    "구리시":"41310",
}

LAWDS = {
    "성동구": SEOUL["성동구"],
    "마포구": SEOUL["마포구"],
    "동작구": SEOUL["동작구"],
    "영등포구": SEOUL["영등포구"],
}
CODE_TO_ADMIN = {v:k for k,v in LAWDS.items()}

DONGTAN_DONGS = {
    "반송동","석우동","능동","청계동","영천동","오산동","목동","산척동","송동",
    "장지동","방교동","신동","금곡동"
}
GWANGGYO_SUWON_DONGS = {"이의동","하동","원천동"}
GWANGGYO_SUJI_DONGS = {"상현동"}
SAMSONG_DONGS = {"삼송동","원흥동","동산동","신원동"}
JICHUK_DONGS = {"지축동"}

def now_kst() -> dt.datetime:
    return dt.datetime.now(dt.timezone(dt.timedelta(hours=9)))

def request_bytes(url: str, timeout: int = 20, tries: int = 3) -> bytes:
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept":"*/*"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except Exception as e:  # noqa: BLE001
            last = e
            if i + 1 < tries:
                time.sleep(1.0 * (i + 1))
    raise RuntimeError(f"request failed: {last}")

def clean(v: Any) -> str:
    return "" if v is None else str(v).strip()

def to_int(v: Any) -> int | None:
    s = clean(v).replace(",","")
    if not s:
        return None
    try:
        return int(float(s))
    except Exception:
        return None

def to_float(v: Any) -> float | None:
    s = clean(v).replace(",","")
    if not s:
        return None
    try:
        return float(s)
    except Exception:
        return None

def norm_name(s: str) -> str:
    s = unicodedata.normalize("NFKC", s or "").lower()
    s = s.replace("아파트","").replace("apt","")
    s = re.sub(r"\([^)]*\)","",s)
    return re.sub(r"[^0-9a-z가-힣]","",s)


def normalize_bjdong_cd(raw: Any, sigungu_cd: str = "") -> str:
    d = re.sub(r"\D", "", clean(raw))
    if not d:
        return ""
    if len(d) >= 10:
        if sigungu_cd and d.startswith(sigungu_cd):
            return d[5:10]
        return d[-5:]
    return d.zfill(5)[-5:]


def parse_jibun(jibun: str) -> tuple[str, str, str] | None:
    """건축HUB 요청용 (platGbCd, bun, ji). 일반대지=0, 산=1."""
    s = clean(jibun).replace(" ", "")
    if not s:
        return None
    plat = "1" if s.startswith("산") else "0"
    if s.startswith("산"):
        s = s[1:]
    m = re.match(r"^(\d+)(?:-(\d+))?$", s)
    if not m:
        return None
    return plat, m.group(1).zfill(4)[-4:], (m.group(2) or "0").zfill(4)[-4:]


def parse_building_rows(raw: bytes) -> list[dict[str, Any]]:
    obj = parse_json_or_xml(raw)
    if isinstance(obj, dict):
        response = obj.get("response", obj)
        header = response.get("header", {}) if isinstance(response, dict) else {}
        code = clean(header.get("resultCode") or (response.get("resultCode") if isinstance(response, dict) else ""))
        if code and code not in {"00", "000"}:
            msg = clean(header.get("resultMsg") or (response.get("resultMsg") if isinstance(response, dict) else ""))
            raise RuntimeError(f"Building HUB {code}: {msg}")
        body = response.get("body", {}) if isinstance(response, dict) else {}
        items = body.get("items", {}) if isinstance(body, dict) else {}
        rows = items.get("item", []) if isinstance(items, dict) else (items or [])
        if isinstance(rows, dict):
            rows = [rows]
        return [r for r in rows if isinstance(r, dict)]
    code = clean(obj.findtext(".//resultCode"))
    if code and code not in {"00", "000"}:
        raise RuntimeError(f"Building HUB {code}: {clean(obj.findtext('.//resultMsg'))}")
    return [{ch.tag: clean(ch.text) for ch in list(it)} for it in obj.findall(".//item")]


def fetch_building_rows(endpoint: str, key: str, sigungu: str, bjdong: str, plat: str, bun: str, ji: str) -> list[dict[str, Any]]:
    params = {
        "serviceKey": urllib.parse.unquote(key),
        "sigunguCd": sigungu,
        "bjdongCd": bjdong,
        "platGbCd": plat,
        "bun": bun,
        "ji": ji,
        "numOfRows": 100,
        "pageNo": 1,
        "_type": "json",
    }
    url = endpoint + "?" + urllib.parse.urlencode(params, safe="%")
    return parse_building_rows(request_bytes(url))


def far_score(row: dict[str, Any], apt_name: str) -> tuple[float, float, float]:
    bld_name = clean(row.get("bldNm"))
    sim = difflib.SequenceMatcher(None, norm_name(apt_name), norm_name(bld_name)).ratio() if bld_name else 0.0
    purps = clean(row.get("mainPurpsCdNm")) + " " + clean(row.get("etcPurps"))
    purpose_bonus = 1.0 if ("공동주택" in purps or "아파트" in purps) else 0.0
    return (purpose_bonus + sim, float(to_int(row.get("hhldCnt")) or 0), float(to_float(row.get("totArea")) or 0))


def pick_recap_far(rows: list[dict[str, Any]], apt_name: str) -> float | None:
    good = [r for r in rows if (to_float(r.get("vlRat")) is not None and 10 <= float(to_float(r.get("vlRat"))) <= 2000)]
    if not good:
        return None
    good.sort(key=lambda r: far_score(r, apt_name), reverse=True)
    return round(float(to_float(good[0].get("vlRat"))), 1)


def pick_title_far(rows: list[dict[str, Any]], apt_name: str) -> float | None:
    vals = [(float(to_float(r.get("vlRat"))), r) for r in rows if to_float(r.get("vlRat")) is not None and 10 <= float(to_float(r.get("vlRat"))) <= 2000]
    if not vals:
        return None
    nums = sorted(v for v, _ in vals)
    # 여러 동의 용적률이 거의 동일할 때만 표제부 fallback 사용.
    if nums[-1] - nums[0] <= 1.0:
        mid = nums[len(nums)//2] if len(nums)%2 else (nums[len(nums)//2-1] + nums[len(nums)//2]) / 2
        return round(mid, 1)
    vals.sort(key=lambda vr: far_score(vr[1], apt_name), reverse=True)
    if far_score(vals[0][1], apt_name)[0] >= 1.65:
        return round(vals[0][0], 1)
    return None


def enrich_far(complexes: dict[str, dict[str, Any]], key: str, cache_path: Path) -> None:
    """건축HUB 총괄표제부의 vlRat를 우선 사용해 용적률을 채운다."""
    if not key:
        print("[far] API key 없음 - 건너뜀", file=sys.stderr)
        return
    try:
        cache = json.loads(cache_path.read_text(encoding="utf-8")) if cache_path.exists() else {}
    except Exception:
        cache = {}
    filled = 0
    consecutive_auth_errors = 0
    targets = list(complexes.values())
    for i, c in enumerate(targets, 1):
        if c.get("far") is not None:
            continue
        sigungu = clean(c.get("sigungu_cd"))
        bjdong = clean(c.get("bjdong_cd"))
        jib = parse_jibun(clean(c.get("jibun")))
        if not (sigungu and bjdong and jib):
            continue
        plat, bun, ji = jib
        ck = "|".join((sigungu, bjdong, plat, bun, ji))
        cached = cache.get(ck)
        if isinstance(cached, dict):
            if cached.get("far") is not None:
                c["far"] = cached["far"]
                c["far_source"] = cached.get("source", "건축HUB 캐시")
                filled += 1
            continue
        try:
            rows = fetch_building_rows(BLD_RECAP_URL, key, sigungu, bjdong, plat, bun, ji)
            far = pick_recap_far(rows, c["name"])
            source = "건축HUB 총괄표제부"
            if far is None:
                rows = fetch_building_rows(BLD_TITLE_URL, key, sigungu, bjdong, plat, bun, ji)
                far = pick_title_far(rows, c["name"])
                source = "건축HUB 표제부" if far is not None else ""
            cache[ck] = {"far": far, "source": source, "name": c["name"]}
            if far is not None:
                c["far"] = far
                c["far_source"] = source
                filled += 1
            consecutive_auth_errors = 0
        except Exception as e:
            msg = str(e)
            print(f"[far] {c['region']} {c['name']} 실패: {msg}", file=sys.stderr)
            if any(x in msg for x in ("PERMISSION", "ACCESS", "SERVICE_KEY", "Building HUB 20:", "Building HUB 30:")):
                consecutive_auth_errors += 1
                if consecutive_auth_errors >= 3:
                    print("[far] 건축HUB 활용신청/서비스키 권한 확인 필요. FAR 보강 중단.", file=sys.stderr)
                    break
            else:
                consecutive_auth_errors = 0
        if i % 100 == 0:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(json.dumps(cache, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
            print(f"[far] {i}/{len(targets)} processed, filled={filled}", flush=True)
        time.sleep(.04)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(cache, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"[far] completed filled={filled}", flush=True)

def xml_text(item: ET.Element, *names: str) -> str:
    for n in names:
        el = item.find(n)
        if el is not None and el.text and el.text.strip():
            return el.text.strip()
    return ""

def month_range(start: str, end: str) -> list[str]:
    sy,sm = map(int,start.split("-"))
    ey,em = map(int,end.split("-"))
    out=[]
    y,m=sy,sm
    while (y,m) <= (ey,em):
        out.append(f"{y:04d}{m:02d}")
        m += 1
        if m == 13:
            y,m = y+1,1
    return out

def region_tags(lawd: str, legal_dong: str) -> list[str]:
    admin = CODE_TO_ADMIN[lawd]
    if lawd in SEOUL.values():
        return [admin]

    if lawd == "41290": return ["과천시"]
    if lawd == "41135": return ["분당시","성남시"]
    if lawd == "41131": return ["수정구","성남시"]
    if lawd == "41133": return ["중원구","성남시"]
    if lawd == "41210": return ["광명시"]
    if lawd == "41450": return ["하남시"]
    if lawd == "41173": return ["평촌동"]
    if lawd == "41465":
        tags=["수지구"]
        if legal_dong in GWANGGYO_SUJI_DONGS:
            tags.append("광교")
        return tags
    if lawd == "41117":
        return ["광교"] if legal_dong in GWANGGYO_SUWON_DONGS else []
    if lawd == "41590":
        return ["동탄시"] if legal_dong in DONGTAN_DONGS else []
    if lawd == "41281":
        tags=[]
        if legal_dong in SAMSONG_DONGS: tags.append("삼송동")
        if legal_dong in JICHUK_DONGS: tags.append("지축")
        return tags
    if lawd in {"41285","41287"}: return ["일산시"]
    if lawd == "41430": return ["의왕시"]
    if lawd == "41310": return ["구리시"]
    return []

def fetch_trade_page(lawd: str, ymd: str, key: str, page: int) -> tuple[list[dict[str,Any]], int | None]:
    params = {
        "serviceKey": urllib.parse.unquote(key),
        "LAWD_CD": lawd,
        "DEAL_YMD": ymd,
        "numOfRows": "1000",
        "pageNo": str(page),
    }
    url = MOLIT_URL + "?" + urllib.parse.urlencode(params, safe="%")
    root = ET.fromstring(request_bytes(url))
    code = clean(root.findtext(".//resultCode"))
    if code and code not in {"00","000"}:
        raise RuntimeError(f"MOLIT {code}: {clean(root.findtext('.//resultMsg'))}")
    total = to_int(root.findtext(".//totalCount"))
    rows=[]
    for item in root.findall(".//item"):
        deal_type = xml_text(item,"dealingGbn","거래유형")
        cancel = xml_text(item,"cdealType","해제여부")
        cancel_day = xml_text(item,"cdealDay","해제사유발생일","해제사유 발생일")
        if "직거래" in deal_type or cancel_day or cancel not in {"","0","N","해제아님"}:
            continue
        name = xml_text(item,"aptNm","아파트")
        area = to_float(xml_text(item,"excluUseAr","전용면적"))
        floor = to_int(xml_text(item,"floor","층"))
        price = to_int(xml_text(item,"dealAmount","거래금액"))
        yy=to_int(xml_text(item,"dealYear","년")); mm=to_int(xml_text(item,"dealMonth","월")); dd=to_int(xml_text(item,"dealDay","일"))
        if not (name and area and floor is not None and price and yy and mm and dd):
            continue
        # 59㎡가 없는 단지는 같은 20평대의 가장 가까운 전용을 대체할 수 있게
        # 전용 49~74.99㎡를 보관한다. 84㎡는 기존 82~86.5㎡ 범위를 유지한다.
        if not (49 <= area < 75 or 82 <= area <= 86.5):
            continue
        legal_dong = xml_text(item,"umdNm","법정동")
        bjdong_cd = normalize_bjdong_cd(xml_text(item,"umdCd","법정동코드"), lawd)
        tags = region_tags(lawd, legal_dong)
        if not tags:
            continue
        apt_seq = xml_text(item,"aptSeq","단지일련번호","아파트일련번호")
        jibun = xml_text(item,"jibun","지번")
        build_year = to_int(xml_text(item,"buildYear","건축년도"))
        road_name = xml_text(item,"roadNm","도로명")
        road_bonbun = xml_text(item,"roadNmBonbun","도로명건물본번호코드")
        road_bubun = xml_text(item,"roadNmBubun","도로명건물부번호코드")
        rows.append({
            "apt_seq": apt_seq,
            "name": name,
            "lawd": lawd,
            "admin_region": CODE_TO_ADMIN[lawd],
            "region_tags": tags,
            "legal_dong": legal_dong,
            "bjdong_cd": bjdong_cd,
            "jibun": jibun,
            "build_year": build_year,
            "area": round(area,2),
            "floor": floor,
            "price": price,
            "date": f"{yy:04d}-{mm:02d}-{dd:02d}",
            "apt_dong": xml_text(item,"aptDong","아파트동","동"),
            "road_name": road_name,
            "road_bonbun": road_bonbun,
            "road_bubun": road_bubun,
        })
    return rows,total

def fetch_trades(lawd: str, ymd: str, key: str) -> list[dict[str,Any]]:
    out=[]
    page=1
    while True:
        rows,total=fetch_trade_page(lawd,ymd,key,page)
        out.extend(rows)
        if total is not None:
            if page*1000 >= total:
                break
        elif len(rows) < 1000:
            break
        page += 1
        if page > 20:
            raise RuntimeError(f"unexpected pagination >20 pages: {lawd} {ymd}")
        time.sleep(.03)
    return out

def complex_key(t: dict[str,Any]) -> str:
    # aptSeq가 있으면 국토부 식별값을 최우선 사용. 없을 때만 복합키.
    if t["apt_seq"]:
        return f"aptseq:{t['apt_seq']}"
    return "|".join([
        t["lawd"], clean(t["legal_dong"]), norm_name(t["name"]), clean(t["jibun"]), str(t["build_year"] or "")
    ])

def collect_trades(start: str, end: str, key: str) -> dict[str,dict[str,Any]]:
    months = month_range(start,end)
    total = len(months)*len(LAWDS)
    done=0
    complexes: dict[str,dict[str,Any]]={}
    seen=set()
    for admin,lawd in LAWDS.items():
        for ym in months:
            done += 1
            print(f"[trade] {done}/{total} {admin} {ym}", flush=True)
            rows=fetch_trades(lawd,ym,key)
            for t in rows:
                ck=complex_key(t)
                c=complexes.get(ck)
                if c is None:
                    c={
                        "id": t["apt_seq"] or ck,
                        "region": t["admin_region"],
                        "region_tags": list(t["region_tags"]),
                        "name": t["name"],
                        "legal_dong": t["legal_dong"],
                        "sigungu_cd": t["lawd"],
                        "bjdong_cd": t.get("bjdong_cd", ""),
                        "jibun": t["jibun"],
                        "address": f"{t['admin_region']} {t['legal_dong']} {t['jibun']}".strip(),
                        "households": None,
                        "completed": str(t["build_year"]) if t["build_year"] else None,
                        "build_year": t["build_year"],
                        "far": None,
                        "top_floor": None,
                        "station": "",
                        "station_display": "",
                        "station_walk_minutes": None,
                        "station_walks": [],
                        "jeonse_tx": [],
                        "naver": "https://new.land.naver.com/search?" + urllib.parse.urlencode({"sk": t["name"]}),
                        "tx": [],
                    }
                    complexes[ck]=c
                else:
                    for tag in t["region_tags"]:
                        if tag not in c["region_tags"]:
                            c["region_tags"].append(tag)
                tup=[t["date"],t["area"],t["floor"],t["price"],t["legal_dong"],t["apt_dong"],t["jibun"]]
                sig=tuple(tup)
                if (ck,sig) not in seen:
                    seen.add((ck,sig))
                    c["tx"].append(tup)
    for c in complexes.values():
        c["tx"].sort(key=lambda x:(x[0],x[1],x[2],x[3]))
    return complexes


def fetch_rent_page(lawd: str, ymd: str, key: str, page: int) -> tuple[list[dict[str,Any]], int | None]:
    params = {
        "serviceKey": urllib.parse.unquote(key),
        "LAWD_CD": lawd,
        "DEAL_YMD": ymd,
        "numOfRows": "1000",
        "pageNo": str(page),
    }
    url = MOLIT_RENT_URL + "?" + urllib.parse.urlencode(params, safe="%")
    root = ET.fromstring(request_bytes(url))
    code = clean(root.findtext(".//resultCode"))
    if code and code not in {"00","000"}:
        raise RuntimeError(f"MOLIT RENT {code}: {clean(root.findtext('.//resultMsg'))}")
    total = to_int(root.findtext(".//totalCount"))
    rows=[]
    for item in root.findall(".//item"):
        name = xml_text(item,"aptNm","아파트")
        area = to_float(xml_text(item,"excluUseAr","전용면적"))
        floor = to_int(xml_text(item,"floor","층"))
        deposit = to_int(xml_text(item,"deposit","보증금액","보증금"))
        monthly = to_int(xml_text(item,"monthlyRent","월세금액","월세")) or 0
        yy=to_int(xml_text(item,"dealYear","년"))
        mm=to_int(xml_text(item,"dealMonth","월"))
        dd=to_int(xml_text(item,"dealDay","일"))
        # 전세 갭에는 순수 전세만 사용
        if monthly != 0:
            continue
        if not (name and area and floor is not None and deposit and yy and mm and dd):
            continue
        if not (49 <= area < 75 or 82 <= area <= 86.5):
            continue
        legal_dong = xml_text(item,"umdNm","법정동")
        tags = region_tags(lawd, legal_dong)
        if not tags:
            continue
        rows.append({
            "apt_seq": xml_text(item,"aptSeq","단지일련번호","아파트일련번호"),
            "name": name,
            "lawd": lawd,
            "legal_dong": legal_dong,
            "jibun": xml_text(item,"jibun","지번"),
            "area": round(area,2),
            "floor": floor,
            "deposit": deposit,
            "date": f"{yy:04d}-{mm:02d}-{dd:02d}",
        })
    return rows,total

def fetch_rents(lawd: str, ymd: str, key: str) -> list[dict[str,Any]]:
    out=[]
    page=1
    while True:
        rows,total=fetch_rent_page(lawd,ymd,key,page)
        out.extend(rows)
        if total is not None:
            if page*1000 >= total:
                break
        elif len(rows) < 1000:
            break
        page += 1
        if page > 20:
            raise RuntimeError(f"unexpected rent pagination >20 pages: {lawd} {ymd}")
        time.sleep(.03)
    return out

def rent_match_key(t: dict[str,Any]) -> tuple[str,str,str,str]:
    return (t["lawd"], clean(t["legal_dong"]), norm_name(t["name"]), clean(t["jibun"]))

def collect_rents_into(complexes: dict[str,dict[str,Any]], start: str, end: str, key: str) -> None:
    by_exact=defaultdict(list)
    by_loose=defaultdict(list)
    for c in complexes.values():
        sig=clean(c.get("sigungu_cd"))
        dong=clean(c.get("legal_dong"))
        name=norm_name(c.get("name","").replace("(임대)",""))
        jib=clean(c.get("jibun"))
        by_exact[(sig,dong,name,jib)].append(c)
        by_loose[(sig,dong,name)].append(c)

    months=month_range(start,end)
    total=len(months)*len(LAWDS)
    done=0
    seen=set()
    for admin,lawd in LAWDS.items():
        for ym in months:
            done+=1
            print(f"[rent] {done}/{total} {admin} {ym}",flush=True)
            try:
                rows=fetch_rents(lawd,ym,key)
            except Exception as e:
                # 전월세 API 활용신청이 아직 안 된 경우에도 매매 사이트 빌드는 계속한다.
                print(f"[rent] skip {admin} {ym}: {e}",file=sys.stderr)
                if "20:" in str(e) or "30:" in str(e) or "PERMISSION" in str(e):
                    print("[rent] 전월세 API 활용신청/권한을 확인하세요.",file=sys.stderr)
                    return
                continue
            for t in rows:
                exact=by_exact.get(rent_match_key(t),[])
                candidates=exact or by_loose.get((t["lawd"],clean(t["legal_dong"]),norm_name(t["name"])),[])
                if len(candidates)!=1:
                    continue
                c=candidates[0]
                tx=[t["date"],t["area"],t["floor"],t["deposit"]]
                k=(c["id"],*tx)
                if k in seen:
                    continue
                seen.add(k)
                c.setdefault("jeonse_tx",[]).append(tx)
    for c in complexes.values():
        c.setdefault("jeonse_tx",[]).sort(key=lambda x:(x[0],x[1],x[2],x[3]))

def parse_walk_minutes(raw: Any) -> int | None:
    s=clean(raw)
    if not s:
        return None
    nums=[int(x) for x in re.findall(r"\d+",s)]
    if not nums:
        return None
    # '5~10분'은 보수적으로 상한 10분, '20분 이내'는 20분
    return max(nums)

def split_station_names(raw: Any) -> list[str]:
    s=clean(raw)
    if not s:
        return []
    parts=re.split(r"[,/·;]+",s)
    out=[]
    for p in parts:
        p=p.strip()
        if not p:
            continue
        if not p.endswith("역"):
            p += "역"
        if p not in out:
            out.append(p)
    return out

def parse_json_or_xml(raw: bytes) -> Any:
    text=raw.decode("utf-8-sig","replace").strip()
    if text.startswith("{") or text.startswith("["):
        return json.loads(text)
    return ET.fromstring(raw)

def kapt_list(key: str) -> list[dict[str,Any]]:
    """서울·경기 K-apt 단지목록. 실패하면 빈 목록으로 돌아가 실거래만 사용한다."""
    all_rows=[]
    for sido in ("11",):
        page=1
        while True:
            params={"serviceKey":urllib.parse.unquote(key),"sidoCode":sido,"pageNo":page,"numOfRows":1000,"_type":"json"}
            url=KAPT_LIST_URL+"?"+urllib.parse.urlencode(params,safe="%")
            try:
                obj=parse_json_or_xml(request_bytes(url))
            except Exception as e:
                print(f"[kapt] list unavailable: {e}",file=sys.stderr)
                return []
            rows=[]
            total=None
            if isinstance(obj,dict):
                body=obj.get("response",{}).get("body",obj.get("body",{}))
                total=to_int(body.get("totalCount"))
                items=body.get("items",{})
                rows=items.get("item",[]) if isinstance(items,dict) else (items or [])
                if isinstance(rows,dict): rows=[rows]
            else:
                code=clean(obj.findtext(".//resultCode"))
                if code and code not in {"00","000"}:
                    print(f"[kapt] list permission/error {code}: {clean(obj.findtext('.//resultMsg'))}",file=sys.stderr)
                    return []
                total=to_int(obj.findtext(".//totalCount"))
                for it in obj.findall(".//item"):
                    rows.append({ch.tag:clean(ch.text) for ch in list(it)})
            all_rows.extend(rows)
            if total is not None and page*1000>=total: break
            if len(rows)<1000: break
            page += 1
    return all_rows

def kapt_basic(kapt_code: str, key: str) -> dict[str,Any] | None:
    params={"serviceKey":urllib.parse.unquote(key),"kaptCode":kapt_code,"_type":"json"}
    url=KAPT_BASIC_URL+"?"+urllib.parse.urlencode(params,safe="%")
    try:
        obj=parse_json_or_xml(request_bytes(url))
    except Exception:
        return None
    if isinstance(obj,dict):
        body=obj.get("response",{}).get("body",obj.get("body",{}))
        item=body.get("item") or body.get("Item")
        if item is None and isinstance(body.get("items"),dict):
            item=body["items"].get("item")
        if isinstance(item,list):
            item=item[0] if item else None
        return item if isinstance(item,dict) else None
    code=clean(obj.findtext(".//resultCode"))
    if code and code not in {"00","000"}:
        return None
    it=obj.find(".//item")
    return {ch.tag:clean(ch.text) for ch in list(it)} if it is not None else None

def enrich_kapt(complexes: dict[str,dict[str,Any]], key: str, cache_path: Path) -> None:
    if not key:
        return
    listing=kapt_list(key)
    if not listing:
        return
    try:
        cache=json.loads(cache_path.read_text(encoding="utf-8")) if cache_path.exists() else {}
    except Exception:
        cache={}
    # K-apt 목록을 법정동코드5자리 + 정규화 단지명으로 인덱스.
    idx=defaultdict(list)
    for r in listing:
        bjd=clean(r.get("bjdCode") or r.get("BJD_CODE"))
        name=clean(r.get("kaptName") or r.get("KAPT_NAME"))
        code=clean(r.get("kaptCode") or r.get("KAPT_CODE"))
        if len(bjd)>=5 and name and code:
            idx[(bjd[:5],norm_name(name))].append((code,bjd))

    targets=list(complexes.values())
    for i,c in enumerate(targets,1):
        lawd=None
        # 거래에서 저장한 admin_region을 코드로 역산
        for k,v in CODE_TO_ADMIN.items():
            if v==c["region"]:
                lawd=k; break
        if not lawd: continue
        codes=idx.get((lawd,norm_name(c["name"])),[])
        if len(codes)!=1:
            continue
        kapt_code,bjd_full=codes[0]
        if not c.get("bjdong_cd"):
            c["bjdong_cd"]=normalize_bjdong_cd(bjd_full, lawd)
        info=cache.get(kapt_code)
        if not isinstance(info,dict):
            info=kapt_basic(kapt_code,key)
            if info:
                cache[kapt_code]=info
        if not info:
            continue
        sale=clean(info.get("codeSaleNm"))
        # 임대 전용 단지는 랭킹에서 빼기 쉽도록 이름에 표시.
        if sale and "임대" in sale and "(임대)" not in c["name"]:
            c["name"] += "(임대)"
        hh=to_int(info.get("kaptdaCnt"))
        used=clean(info.get("kaptUsedate"))
        # 일부 K-apt/확장 응답에는 최고층 필드가 있을 수 있어 있으면 우선 저장한다.
        top=to_int(info.get("kaptTopFloor") or info.get("highestFloor") or info.get("maxFloor") or info.get("topFloor"))
        if hh is not None: c["households"]=hh
        if top is not None and top>0: c["top_floor"]=top
        if len(re.sub(r"\D","",used))>=6:
            d=re.sub(r"\D","",used)
            c["completed"]=f"{d[:4]}.{d[4:6]}"
        addr=clean(info.get("doroJuso") or info.get("kaptAddr"))
        if addr: c["address"]=addr

        station_raw=clean(
            info.get("subwayStation") or info.get("SUBWAY_STATION") or
            info.get("subway_station") or info.get("subwayStn")
        )
        line_raw=clean(
            info.get("subwayLine") or info.get("SUBWAY_LINE") or
            info.get("subway_line")
        )
        walk_raw=(
            info.get("kaptdWtimesub") or info.get("KAPTD_WTIMESUB") or
            info.get("kaptd_wtimesub") or info.get("wtimeSubway")
        )
        walk_min=parse_walk_minutes(walk_raw)
        stations=split_station_names(station_raw)
        if stations:
            c["station"]=stations[0].replace("역","")
            c["station_display"]=((line_raw + " ") if line_raw else "") + stations[0]
            c["station_walk_minutes"]=walk_min
            c["station_walks"]=[
                {"name":name,"minutes":walk_min,"line":line_raw}
                for name in stations if walk_min is not None
            ]
        if i%100==0:
            print(f"[kapt] enriched {i}/{len(targets)}",flush=True)
        time.sleep(.04)

    cache_path.parent.mkdir(parents=True,exist_ok=True)
    cache_path.write_text(json.dumps(cache,ensure_ascii=False,separators=(",",":")),encoding="utf-8")
    print(f"[kapt] cache saved: {len(cache)}",flush=True)

def main() -> None:
    ap=argparse.ArgumentParser()
    ap.add_argument("--start",default="2025-07")
    ap.add_argument("--end",default=None,help="YYYY-MM; default current KST month")
    ap.add_argument("--mode",default="full",choices=["full","incremental"],help="현재는 정확도 우선으로 두 모드 모두 지정 기간을 재구축")
    ap.add_argument("--output",default=str(OUT_DEFAULT))
    ap.add_argument("--skip-kapt",action="store_true",help="4개구 세대수/사용승인일/인근역 K-apt 보강 생략")
    ap.add_argument("--skip-far",action="store_true",help="건축HUB 용적률 보강 생략")
    ap.add_argument("--far-cache",default="data/far-cache.json",help="건축HUB 용적률 캐시")
    ap.add_argument("--kapt-cache",default="data/kapt-cache.json",help="K-apt 기본정보 캐시")
    args=ap.parse_args()

    key=os.environ.get("PUBLIC_DATA_API_KEY") or os.environ.get("MOLIT_API_KEY") or ""
    if not key:
        raise SystemExit("PUBLIC_DATA_API_KEY 환경변수가 필요합니다.")
    end=args.end or now_kst().strftime("%Y-%m")
    complexes=collect_trades(args.start,end,key)
    collect_rents_into(complexes,args.start,end,key)

    if not args.skip_kapt:
        kapt_key=os.environ.get("KAPT_API_KEY") or key
        enrich_kapt(complexes,kapt_key,Path(args.kapt_cache))

    if not args.skip_far:
        building_key=os.environ.get("BUILDING_HUB_API_KEY") or key
        enrich_far(complexes, building_key, Path(args.far_cache))

    # 거래 없는 메타 단지는 넣지 않는다. 이 사이트는 가격 비교가 목적.
    arr=list(complexes.values())
    arr.sort(key=lambda c:(c["region"],c["legal_dong"],c["name"]))

    loaded_tags=set()
    for c in arr:
        loaded_tags.update(c.get("region_tags") or [c["region"]])

    out={
        "meta":{
            "status":"pilot_4_districts",
            "updated_at":now_kst().strftime("%Y-%m-%d %H:%M KST"),
            "current_month":end,
            "min_month":args.start,
            "loaded_regions":sorted(loaded_tags),
            "complex_count":len(arr),
            "note":"파일럿 v13: 성동구·마포구·동작구·영등포구 4개구의 매매·전세 실거래. 59㎡가 없으면 같은 20평대의 가장 가까운 전용을 대체하고, 역세권은 K-apt 인근역 도보시간 20분 이내를 우선 사용.",
            "sources":{
                "trades":"국토교통부 아파트 매매 실거래가 상세 자료",
                "rent":"국토교통부 아파트 전월세 실거래가 자료(월세 0원인 순수 전세)",
                "metadata":"성동·마포·동작·영등포 세대수/사용승인일/인근역은 K-apt 기본정보 API 매칭 가능 단지에 한해 보강",
                "far":"국토교통부 건축HUB 건축물대장정보 서비스 총괄표제부(vlRat) 우선",
                "station":"K-apt 기본정보의 인근 지하철역/도보시간. UI는 20분 이내만 역 필터에 포함"
            },
            "top_floor_rule":"K-apt 등에서 확인된 최상층이 있으면 사용하고, 없으면 수집기간 내 관측 최고층을 대용값으로 사용"
        },
        "complexes":arr
    }
    p=Path(args.output)
    p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(out,ensure_ascii=False,separators=(",",":")),encoding="utf-8")
    print(f"[done] {p} complexes={len(arr)} size={p.stat().st_size/1024/1024:.2f}MB")

if __name__=="__main__":
    main()
