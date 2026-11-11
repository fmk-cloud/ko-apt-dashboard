"""Refresh the latest twelve closed months; fill a longer gap when needed."""
import re

def shift(month,delta):
    year,m=map(int,month.split('-'));number=year*12+m-1+delta
    return f'{number//12:04}-{number%12+1:02}'

def refresh_start(snapshot,configured_start,end,full=False):
    meta=snapshot.get('meta',{})
    previous=meta.get('current_month','')
    if full or not meta.get('source_verified') or meta.get('provider')!='seoul_gyeonggi_official' or not re.fullmatch(r'\d{4}-(0[1-9]|1[0-2])',previous):
        return configured_start
    return max(configured_start,min(shift(end,-11),shift(previous,1)))
