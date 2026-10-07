#!/usr/bin/env python3
# Backward-compatible entry point; no API key required.
from pathlib import Path
from update_all import run_all
if __name__=='__main__': run_all(Path(__file__).resolve().parents[1])
