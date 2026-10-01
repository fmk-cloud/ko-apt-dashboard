#!/usr/bin/env python3
from __future__ import annotations
import json, re, sys
from collections import Counter
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
EXPECTED=["영등포구","마포구","성동구","동작구"]

def validate(full: bool) -> None:
    data=json.loads((ROOT/"data"/"site-data.json").read_text(encoding="utf-8"))
    html=(ROOT/"index.html").read_text(encoding="utf-8")
    assert "k APT Dashboard v19" in html
    # v18 UI behavior must remain present.
    required_js=[
        "function filterComplex(c)",
        "const lowFloorExcluded=rows.filter(t=>t.floor<=3)",
        "if(!band.length){",
        "let DATA = window.__EMBEDDED_DATA__;",
        'id="popLoad"',
        "FILTER_PRESET_KEY='koAptDashboardFilterPresetV18'",
    ]
    for token in required_js:
        assert token in html, f"missing v18 UI token: {token}"
    m=re.search(r'window\.__EMBEDDED_DATA__=(\{.*?\});</script>',html,re.S)
    assert m, "embedded data block missing"
    embedded=json.loads(m.group(1))
    assert embedded==data, "index embedded data differs from data/site-data.json"
    counts=Counter(c.get("region") for c in data.get("complexes",[]))
    assert counts.get("영등포구",0)>=100
    assert counts.get("마포구",0)>=80
    assert counts.get("성동구",0)>=80
    if full:
        assert data["meta"]["status"]=="full_v19_4gu"
        assert data["meta"]["loaded_regions"]==EXPECTED
        assert counts.get("동작구",0)>=50, counts
        for r in EXPECTED:
            st=data["meta"]["region_stats"][r]
            assert st["months_succeeded"]>=1
            assert st["transaction_count"]>0
    print("validate_build OK",dict(counts),data["meta"].get("status"))

if __name__=="__main__":
    validate("--full" in sys.argv)
