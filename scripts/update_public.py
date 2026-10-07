#!/usr/bin/env python3
from pathlib import Path
import sys
from update_all import run_all
from pipeline import DataError
if __name__=='__main__':
 try:run_all(Path(__file__).resolve().parents[1])
 except DataError as e:print('수집 중단:',e,file=sys.stderr);sys.exit(1)
