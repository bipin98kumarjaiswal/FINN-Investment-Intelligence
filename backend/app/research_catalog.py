"""Refresh authentic NSE-listed company symbols. Cached for offline search."""
import csv
import io
import re
import argparse
import requests
from app import research_store

EQUITY_CSV = 'https://archives.nseindia.com/content/equities/EQUITY_L.csv'


def parse_catalog(csv_text: str):
    rows=list(csv.DictReader(io.StringIO(csv_text.lstrip('\ufeff'))))
    if not rows:
        raise ValueError('NSE CSV returned zero company rows')
    result=[]
    for raw in rows:
        normalized={k.strip().upper(): (v or '').strip() for k,v in raw.items() if k}
        symbol=normalized.get('SYMBOL','').upper()
        name=normalized.get('NAME OF COMPANY','')
        series=normalized.get('SERIES','')
        if re.fullmatch(r'[A-Z0-9&-]{1,25}',symbol) and name and series in ('EQ','BE','BZ','SM','ST'):
            result.append({'symbol':symbol,'name':name})
    if len(result)<100:
        raise ValueError(f'Unexpected NSE catalog size ({len(result)}); source schema may have changed')
    return result


def refresh_catalog(get=None, path=None):
    get = get or requests.get
    resp=get(EQUITY_CSV,headers={'User-Agent':'Mozilla/5.0','Accept':'text/csv,*/*'},timeout=25)
    resp.raise_for_status()
    rows=parse_catalog(resp.content.decode('utf-8-sig'))
    return {'source':EQUITY_CSV,'saved':research_store.save_catalog(rows,path)}


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--refresh',action='store_true')
    args=parser.parse_args()
    if args.refresh:
        try: print(refresh_catalog())
        except Exception as exc:
            print(f'NSE equity catalog unavailable: {type(exc).__name__}: {exc}')
            raise SystemExit(1)
    else: parser.print_help()
