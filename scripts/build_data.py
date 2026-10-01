#!/usr/bin/env python3
"""Local full build for the four-district v19 pilot.

GitHub Actions uses the same collect_region.py per district in parallel. This wrapper
runs the identical pipeline sequentially for local verification when network/API keys
are available.
"""
from __future__ import annotations
import argparse, json, os, shutil, subprocess, sys, tempfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
REGIONS=["영등포구","마포구","성동구","동작구"]

def run(cmd:list[str])->None:
    print("+"," ".join(cmd),flush=True)
    subprocess.run(cmd,cwd=ROOT,check=True)

def main()->None:
    ap=argparse.ArgumentParser()
    ap.add_argument("--start",default="2022-09")
    ap.add_argument("--end",default=None)
    args=ap.parse_args()
    if not (os.environ.get("PUBLIC_DATA_API_KEY") or os.environ.get("MOLIT_API_KEY")):
        raise SystemExit("PUBLIC_DATA_API_KEY secret is missing")
    parts=ROOT/"parts-local"
    if parts.exists(): shutil.rmtree(parts)
    parts.mkdir()
    for i,region in enumerate(REGIONS):
        cmd=[sys.executable,"scripts/collect_region.py","--region",region,"--start",args.start,"--out",str(parts/f"region-{i}.json")]
        if args.end: cmd.extend(["--end",args.end])
        run(cmd)
    run([sys.executable,"scripts/merge_regions.py","--parts",str(parts),"--out","data/site-data.json"])
    run([sys.executable,"scripts/embed_data.py"])
    run([sys.executable,"scripts/validate_build.py","--full"])
    shutil.rmtree(parts)

if __name__=="__main__": main()
