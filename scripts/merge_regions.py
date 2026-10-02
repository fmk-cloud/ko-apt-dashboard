#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXPECTED = ["영등포구", "마포구", "성동구", "동작구"]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--parts", required=True)
    ap.add_argument("--out", default=str(ROOT / "data" / "site-data.json"))
    args = ap.parse_args()

    part_dir = Path(args.parts)
    parts = sorted(part_dir.rglob("*.json"))
    if not parts:
        raise SystemExit("no region part files")

    by_region = {}
    current_month = ""
    min_month = "9999-99"
    for p in parts:
        d = json.loads(p.read_text(encoding="utf-8"))
        meta = d.get("meta", {})
        region = meta.get("region")
        if meta.get("status") != "region_ok" or region not in EXPECTED:
            raise SystemExit(f"invalid part: {p} meta={meta}")
        if meta.get("months_requested") != meta.get("months_succeeded"):
            raise SystemExit(f"incomplete month collection: {region}")
        if region in by_region:
            raise SystemExit(f"duplicate region part: {region}")
        by_region[region] = d
        current_month = max(current_month, meta.get("current_month", ""))
        min_month = min(min_month, meta.get("min_month", "9999-99"))

    missing = [r for r in EXPECTED if r not in by_region]
    if missing:
        raise SystemExit(f"missing region parts: {missing}")

    complexes = []
    region_stats = {}
    for region in EXPECTED:
        d = by_region[region]
        complexes.extend(d.get("complexes", []))
        m = d["meta"]
        region_stats[region] = {
            "complex_count": m.get("complex_count", 0),
            "complexes_with_trades": m.get("complexes_with_trades", 0),
            "transaction_count": m.get("transaction_count", 0),
            "months_succeeded": m.get("months_succeeded", 0),
        }

    # Duplicate guard: region + name + address should be unique after each regional collector dedupes metadata.
    seen = set()
    for c in complexes:
        key = (c.get("region"), c.get("name"), c.get("address"))
        if key in seen:
            raise SystemExit(f"duplicate complex after merge: {key}")
        seen.add(key)

    now = dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).strftime("%Y-%m-%d %H:%M KST")
    out = {
        "meta": {
            "status": "full_v20_4gu",
            "updated_at": now,
            "current_month": current_month,
            "min_month": min_month,
            "loaded_regions": EXPECTED,
            "complex_count": len(complexes),
            "region_stats": region_stats,
            "note": "v20 검증 범위: 영등포구·마포구·성동구·동작구. 각 구를 독립 수집·검증한 뒤 모두 성공한 경우에만 병합합니다.",
            "sources": {
                "trades": "국토교통부 아파트 매매 실거래가 상세 자료",
                "metadata": "서울 열린데이터광장 OA-15818 기반 공개 메타데이터 캐시",
                "far": "v18에서 검증·보존된 값 우선; 미확인 단지는 null"
            }
        },
        "complexes": complexes,
    }
    p = Path(args.out)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print("merged", len(complexes), "complexes", region_stats)


if __name__ == "__main__":
    main()
