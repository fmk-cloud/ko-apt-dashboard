#!/usr/bin/env python3
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
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
REGIONS = json.loads((ROOT / "data" / "regions.json").read_text(encoding="utf-8"))
META_URL = "https://raw.githubusercontent.com/wmjoo/seoul_apt/main/seoul_apartments_metadata.csv"
MOLIT_URL = "https://apis.data.go.kr/1613000/RTMSDataSvcAptTradeDev/getRTMSDataSvcAptTradeDev"
UA = "k-apt-dashboard-v19-four-districts/1.0"

STATION_LINES = {
    # 영등포구
    "당산":"2,9", "영등포구청":"2,5", "문래":"2", "영등포":"1", "신길":"1,5",
    "대림":"2,7", "도림천":"2", "양평":"5", "여의도":"5,9", "여의나루":"5",
    "샛강":"9,신림", "국회의사당":"9", "영등포시장":"5", "보라매":"7,신림",
    "신풍":"7", "신대방삼거리":"7", "대방":"1,신림",
    # 성동구
    "왕십리":"2,5,경의중앙,수인분당", "서울숲":"수인분당", "성수":"2", "뚝섬":"2",
    "옥수":"3,경의중앙", "금호":"3", "신금호":"5", "행당":"5", "마장":"5",
    "상왕십리":"2", "응봉":"경의중앙", "한양대":"2", "용답":"2", "신답":"2",
    # 마포구
    "공덕":"5,6,경의중앙,공항", "마포":"5", "대흥":"6", "광흥창":"6", "상수":"6",
    "합정":"2,6", "홍대입구":"2,경의중앙,공항", "애오개":"5", "아현":"2", "신촌":"2",
    "이대":"2", "서강대":"경의중앙", "망원":"6", "월드컵경기장":"6", "마포구청":"6",
    "디지털미디어시티":"6,경의중앙,공항", "가좌":"경의중앙",
    # 동작구
    "노량진":"1,9", "노들":"9", "흑석":"9", "동작":"4,9", "상도":"7", "장승배기":"7",
    "숭실대입구":"7", "남성":"7", "이수":"4,7", "총신대입구":"4,7", "사당":"2,4",
    "신대방":"2", "신대방삼거리":"7", "보라매":"7,신림", "대방":"1,신림"
}


def clean_text(v: Any) -> str:
    return "" if v is None else str(v).strip()


def first_value(row: dict[str, Any], candidates: Iterable[str]) -> str:
    for key in candidates:
        v = row.get(key)
        if v is not None and str(v).strip() not in ("", "nan", "None"):
            return str(v).strip()
    return ""


def to_number(v: Any) -> float | None:
    s = clean_text(v).replace(",", "").replace("%", "")
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
    return re.sub(r"[^0-9a-z가-힣]", "", s)


def norm_station(s: str) -> str:
    return clean_text(s).replace("역", "").strip()


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


def request_bytes(url: str, timeout: int = 60, tries: int = 5) -> bytes:
    last: Exception | None = None
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except Exception as exc:  # noqa: BLE001
            last = exc
            if attempt + 1 < tries:
                time.sleep(2.0 * (attempt + 1))
    raise RuntimeError(f"request failed after {tries} tries: {last}")


def load_metadata(region: str, raw: bytes | None = None, min_complexes: int = 20) -> list[dict[str, Any]]:
    if raw is None:
        raw = request_bytes(META_URL, timeout=90)
    rows = csv.DictReader(io.StringIO(raw.decode("utf-8-sig", errors="replace")))
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for row in rows:
        district = first_value(row, ["자치구", "SGG_ADDR", "원본_SGG_ADDR", "SGG_NM"])
        if region not in district:
            continue
        name = first_value(row, ["아파트명", "APT_NM", "원본_APT_NM"])
        if not name:
            continue
        address = first_value(row, ["주소", "APT_RDN_ADDR", "원본_APT_RDN_ADDR", "원본_APT_STDG_ADDR"])
        key = (region, norm_name(name), address)
        if key in seen:
            continue
        seen.add(key)
        completed = format_completed(row)
        build_year = to_int(first_value(row, ["건축연도", "build_year", "BUILD_YEAR"]))
        if build_year is None and completed and completed[:4].isdigit():
            build_year = int(completed[:4])
        station = norm_station(first_value(row, ["가장가까운지하철역", "nearest_station", "지하철역"]))
        out.append({
            "id": first_value(row, ["원본_APT_CD", "APT_CD", "단지코드"]) or f"{REGIONS[region]}-meta-{len(out)+1}",
            "region": region,
            "region_tags": [region],
            "name": name,
            "address": address,
            "households": to_int(first_value(row, ["세대수", "TNOHSH", "원본_TNOHSH", "TOT_HSHLD_CO"])),
            "completed": completed,
            "build_year": build_year,
            "station": station,
            "station_display": station_display(station),
            "station_distance_km": to_number(first_value(row, ["지하철역거리_km", "station_distance_km"])),
            "lat": to_number(first_value(row, ["위도", "LAT", "Y"])),
            "lon": to_number(first_value(row, ["경도", "LNG", "LON", "X"])),
            "far": None,
            "legal_dong": first_value(row, ["원본_EMD_ADDR", "EMD_ADDR"]),
            "sigungu_cd": REGIONS[region],
            "naver": "https://new.land.naver.com/search?" + urllib.parse.urlencode({"sk": name}),
            "tx": [],
        })
    if len(out) < min_complexes:
        raise RuntimeError(f"metadata too small for {region}: {len(out)}")
    return out


def xml_text(item: ET.Element, names: list[str]) -> str:
    for name in names:
        el = item.find(name)
        if el is not None and el.text and el.text.strip():
            return el.text.strip()
    return ""


def month_range(start: str, end: str) -> list[str]:
    sy, sm = map(int, start.split("-"))
    ey, em = map(int, end.split("-"))
    out: list[str] = []
    y, m = sy, sm
    while (y, m) <= (ey, em):
        out.append(f"{y:04d}{m:02d}")
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return out


def fetch_page(lawd: str, ymd: str, key: str, page: int) -> tuple[list[dict[str, Any]], int | None]:
    params = {
        "serviceKey": urllib.parse.unquote(key),
        "LAWD_CD": lawd,
        "DEAL_YMD": ymd,
        "numOfRows": "1000",
        "pageNo": str(page),
    }
    url = MOLIT_URL + "?" + urllib.parse.urlencode(params, safe="%")
    root = ET.fromstring(request_bytes(url, timeout=60))
    code = clean_text(root.findtext(".//resultCode"))
    msg = clean_text(root.findtext(".//resultMsg"))
    if code and code not in {"00", "000"}:
        raise RuntimeError(f"MOLIT {code}: {msg}")
    total = to_int(root.findtext(".//totalCount"))
    rows: list[dict[str, Any]] = []
    for item in root.findall(".//item"):
        deal_type = xml_text(item, ["dealingGbn", "거래유형"])
        cancel_type = xml_text(item, ["cdealType", "해제여부"])
        cancel_day = xml_text(item, ["cdealDay", "해제사유발생일", "해제사유 발생일"])
        if "직거래" in deal_type or cancel_day or cancel_type not in {"", "0", "N", "해제아님"}:
            continue
        name = xml_text(item, ["aptNm", "아파트"])
        area = to_number(xml_text(item, ["excluUseAr", "전용면적"]))
        floor = to_int(xml_text(item, ["floor", "층"]))
        price = to_int(xml_text(item, ["dealAmount", "거래금액"]))
        yy = to_int(xml_text(item, ["dealYear", "년"]))
        mm = to_int(xml_text(item, ["dealMonth", "월"]))
        dd = to_int(xml_text(item, ["dealDay", "일"]))
        if not (name and area is not None and floor is not None and price and yy and mm and dd):
            continue
        # UI에서 59㎡가 없으면 같은 20평대(45~74.99㎡) 중 59㎡에 가장 가까운 타입을 선택한다.
        # 84㎡는 기존 허용 오차를 유지한다. 저층/최고층 제외는 브라우저 로직이 담당하므로 여기서 층을 버리지 않는다.
        if not (45 <= area < 75 or 82 <= area <= 86.5):
            continue
        rows.append({
            "name": name,
            "legal_dong": xml_text(item, ["umdNm", "법정동"]),
            "jibun": xml_text(item, ["jibun", "지번"]),
            "apt_seq": xml_text(item, ["aptSeq", "단지일련번호", "아파트일련번호"]),
            "build_year": to_int(xml_text(item, ["buildYear", "건축년도"])),
            "area_m2": round(area, 2),
            "floor": floor,
            "price_10k": price,
            "deal_date": f"{yy:04d}-{mm:02d}-{dd:02d}",
        })
    return rows, total


def fetch_month(lawd: str, ymd: str, key: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    page = 1
    while True:
        rows, total = fetch_page(lawd, ymd, key, page)
        out.extend(rows)
        if total is not None and page * 1000 >= total:
            break
        if total is None and len(rows) < 1000:
            break
        page += 1
        if page > 20:
            raise RuntimeError(f"unexpected pagination >20: {lawd} {ymd}")
    return out


def candidate_score(meta: dict[str, Any], trade: dict[str, Any]) -> float:
    a = norm_name(meta.get("name", ""))
    b = norm_name(trade.get("name", ""))
    if not a or not b:
        return 0.0
    if a == b:
        score = 1.0
    elif a in b or b in a:
        score = 0.92
    else:
        score = difflib.SequenceMatcher(None, a, b).ratio()
    by = trade.get("build_year")
    my = meta.get("build_year")
    if by and my:
        diff = abs(int(by) - int(my))
        if diff == 0:
            score += 0.05
        elif diff <= 2:
            score += 0.02
        elif diff >= 7:
            score -= 0.12
    ld = clean_text(trade.get("legal_dong"))
    md = clean_text(meta.get("legal_dong"))
    if ld and md:
        if ld == md:
            score += 0.04
        elif ld not in md and md not in ld:
            score -= 0.04
    return score


def build_matcher(complexes: list[dict[str, Any]]) -> dict[str, Any]:
    exact: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for c in complexes:
        exact[norm_name(c["name"])].append(c)
    return {"exact": exact, "all": complexes}


def match_complex(matcher: dict[str, Any], trade: dict[str, Any]) -> dict[str, Any] | None:
    key = norm_name(trade.get("name", ""))
    exact = matcher["exact"].get(key, [])
    pool = exact or matcher["all"]
    scored = sorted(((candidate_score(c, trade), c) for c in pool), key=lambda x: x[0], reverse=True)
    if not scored:
        return None
    threshold = 0.74 if exact else 0.80
    return scored[0][1] if scored[0][0] >= threshold else None


def make_trade_only_complex(region: str, trade: dict[str, Any], seq: int) -> dict[str, Any]:
    name = clean_text(trade.get("name"))
    by = trade.get("build_year")
    return {
        "id": trade.get("apt_seq") or f"{REGIONS[region]}-trade-{seq}",
        "region": region,
        "region_tags": [region],
        "name": name,
        "address": f"서울특별시 {region} {clean_text(trade.get('legal_dong'))} {clean_text(trade.get('jibun'))}".strip(),
        "households": None,
        "completed": f"{by}.01" if by else None,
        "build_year": by,
        "station": "",
        "station_display": "",
        "station_distance_km": None,
        "lat": None,
        "lon": None,
        "far": None,
        "legal_dong": clean_text(trade.get("legal_dong")),
        "sigungu_cd": REGIONS[region],
        "naver": "https://new.land.naver.com/search?" + urllib.parse.urlencode({"sk": name}),
        "tx": [],
    }


def merge_seed_metadata(complexes: list[dict[str, Any]], region: str) -> None:
    p = ROOT / "data" / "metadata-seed.json"
    if not p.exists():
        return
    seed = json.loads(p.read_text(encoding="utf-8"))
    by_norm: dict[str, dict[str, Any]] = {}
    for key, md in seed.items():
        if not key.startswith(region + "|"):
            continue
        by_norm[norm_name(md.get("name", ""))] = md
    keep = [
        "id", "address", "households", "completed", "build_year", "station", "station_display",
        "station_distance_km", "station_walk_minutes", "station_walks", "lat", "lon", "far",
        "far_source", "top_floor", "naver"
    ]
    for c in complexes:
        md = by_norm.get(norm_name(c.get("name", "")))
        if not md:
            continue
        for k in keep:
            v = md.get(k)
            if v not in (None, "", []):
                c[k] = v


def collect(region: str, start: str, end: str, key: str) -> dict[str, Any]:
    if region not in REGIONS:
        raise SystemExit(f"unsupported region: {region}")
    complexes = load_metadata(region)
    matcher = build_matcher(complexes)
    lawd = REGIONS[region]
    months = month_range(start, end)
    unmatched = Counter()
    query_count = 0
    raw_trade_count = 0
    for idx, ym in enumerate(months, 1):
        print(f"[trade] {region} {idx}/{len(months)} {ym}", flush=True)
        rows = fetch_month(lawd, ym, key)
        query_count += 1
        raw_trade_count += len(rows)
        for t in rows:
            c = match_complex(matcher, t)
            if c is None:
                unmatched[norm_name(t.get("name", ""))] += 1
                # A newly completed / missing-metadata complex is still retained rather than silently dropped.
                c = make_trade_only_complex(region, t, len(complexes) + 1)
                complexes.append(c)
                matcher = build_matcher(complexes)
            c["tx"].append([t["deal_date"], t["area_m2"], t["floor"], t["price_10k"]])
        time.sleep(0.08)

    # Dedupe and stable-sort transaction arrays.
    for c in complexes:
        seen: set[tuple[Any, ...]] = set()
        tx: list[list[Any]] = []
        for x in sorted(c.get("tx", []), key=lambda z: (z[0], z[1], z[2], z[3])):
            sig = tuple(x)
            if sig not in seen:
                seen.add(sig)
                tx.append(x)
        c["tx"] = tx

    merge_seed_metadata(complexes, region)
    trade_count = sum(len(c.get("tx", [])) for c in complexes)
    with_trades = sum(bool(c.get("tx")) for c in complexes)
    if query_count != len(months):
        raise RuntimeError(f"query count mismatch {query_count} != {len(months)}")
    if trade_count == 0 or with_trades == 0:
        raise RuntimeError(f"no usable transactions collected for {region}")

    now = dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).strftime("%Y-%m-%d %H:%M KST")
    return {
        "meta": {
            "status": "region_ok",
            "region": region,
            "lawd_cd": lawd,
            "updated_at": now,
            "current_month": end,
            "min_month": start,
            "months_requested": len(months),
            "months_succeeded": query_count,
            "complex_count": len(complexes),
            "complexes_with_trades": with_trades,
            "transaction_count": trade_count,
            "raw_filtered_trade_count": raw_trade_count,
            "unmatched_trade_name_count": sum(unmatched.values()),
        },
        "complexes": sorted(complexes, key=lambda c: (c.get("legal_dong", ""), c.get("name", ""))),
    }


def self_test() -> None:
    csv_text = """자치구,주소,아파트명,건축연도,세대수,가장가까운지하철역,지하철역거리_km,위도,경도,원본_APT_CD,원본_SGG_ADDR,원본_EMD_ADDR,원본_USE_APRV_YMD\n동작구,서울특별시 동작구 테스트로 1,테스트아파트,2005,500,상도역,0.25,37.5,126.9,A1,동작구,상도동,2005-06-30\n""".encode()
    md = load_metadata("동작구", raw=csv_text, min_complexes=1)
    assert md[0]["households"] == 500
    assert md[0]["station"] == "상도"
    assert md[0]["station_display"] == "7상도"
    trade = {"name": "테스트", "build_year": 2005, "legal_dong": "상도동"}
    assert match_complex(build_matcher(md), trade) is md[0]
    assert month_range("2025-11", "2026-02") == ["202511", "202512", "202601", "202602"]
    print("collect_region self-test OK")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--region")
    ap.add_argument("--start", default="2022-09")
    ap.add_argument("--end", default=None)
    ap.add_argument("--out")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        self_test()
        return
    if not args.region or not args.out:
        raise SystemExit("--region and --out are required")
    key = os.environ.get("PUBLIC_DATA_API_KEY") or os.environ.get("MOLIT_API_KEY") or ""
    if not key:
        raise SystemExit("PUBLIC_DATA_API_KEY secret is missing")
    end = args.end or dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).strftime("%Y-%m")
    payload = collect(args.region, args.start, end, key)
    p = Path(args.out)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"[done] {args.region}: complexes={payload['meta']['complex_count']} tx={payload['meta']['transaction_count']} -> {p}")


if __name__ == "__main__":
    main()
