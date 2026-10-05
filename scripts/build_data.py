#!/usr/bin/env python3
# Backward-compatible entry point; no API key required.
from pathlib import Path
from seoul_public import run_public
if __name__=='__main__': run_public(Path(__file__).resolve().parents[1])
