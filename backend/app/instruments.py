"""Indian-market instrument search using Fyers' public symbol masters."""
import csv
import io
import threading
import time

import requests

SOURCES = {
    "NSE cash & indices": "https://public.fyers.in/sym_details/NSE_CM.csv",
    "NSE futures & options": "https://public.fyers.in/sym_details/NSE_FO.csv",
    "NSE currency": "https://public.fyers.in/sym_details/NSE_CD.csv",
    "BSE cash & indices": "https://public.fyers.in/sym_details/BSE_CM.csv",
    "BSE futures & options": "https://public.fyers.in/sym_details/BSE_FO.csv",
    "MCX commodities": "https://public.fyers.in/sym_details/MCX_COM.csv",
}

# Always available even if the public master is temporarily unreachable.
MAJOR_INDICES = [
    ("NIFTY / NIFTY 50", "NSE:NIFTY50-INDEX"),
    ("BANK NIFTY", "NSE:NIFTYBANK-INDEX"),
    ("MIDCAP NIFTY", "NSE:MIDCPNIFTY-INDEX"),
    ("FIN NIFTY", "NSE:FINNIFTY-INDEX"),
    ("NIFTY NEXT 50", "NSE:NIFTYNXT50-INDEX"),
    ("NIFTY 100", "NSE:NIFTY100-INDEX"),
    ("NIFTY 200", "NSE:NIFTY200-INDEX"),
    ("NIFTY 500", "NSE:NIFTY500-INDEX"),
    ("NIFTY IT", "NSE:NIFTYIT-INDEX"),
    ("NIFTY AUTO", "NSE:NIFTYAUTO-INDEX"),
    ("NIFTY PHARMA", "NSE:NIFTYPHARMA-INDEX"),
    ("NIFTY FMCG", "NSE:NIFTYFMCG-INDEX"),
    ("NIFTY METAL", "NSE:NIFTYMETAL-INDEX"),
    ("NIFTY REALTY", "NSE:NIFTYREALTY-INDEX"),
    ("NIFTY ENERGY", "NSE:NIFTYENERGY-INDEX"),
    ("NIFTY PSU BANK", "NSE:NIFTYPSUBANK-INDEX"),
    ("SENSEX", "BSE:SENSEX-INDEX"),
    ("BANKEX", "BSE:BANKEX-INDEX"),
]
_cache = []
_cache_at = 0.0
_lock = threading.Lock()


def _load():
    global _cache, _cache_at
    if _cache and time.monotonic() - _cache_at < 6 * 3600:
        return _cache
    with _lock:
        if _cache and time.monotonic() - _cache_at < 6 * 3600:
            return _cache
        rows = [{"name": name, "symbol": symbol, "segment": "Major indices"} for name,symbol in MAJOR_INDICES]
        seen = {x["symbol"] for x in rows}
        for segment,url in SOURCES.items():
            try:
                response=requests.get(url,timeout=20); response.raise_for_status()
                for record in csv.reader(io.StringIO(response.text)):
                    # Fyers public masters have no header: description=1,
                    # provider symbol=9, short/underlying name=13.
                    if len(record) <= 13 or not record[9] or ":" not in record[9]: continue
                    symbol=record[9].strip()
                    if symbol in seen: continue
                    seen.add(symbol)
                    rows.append({"name":(record[1] or record[13] or symbol).strip(),"symbol":symbol,"segment":segment})
            except requests.RequestException:
                continue
        _cache, _cache_at = rows, time.monotonic()
        return rows


def search_instruments(query="", segment=None, limit=100):
    terms=query.upper().split()
    matches=[]
    for item in _load():
        if segment and item["segment"] != segment: continue
        haystack=f'{item["name"]} {item["symbol"]}'.upper()
        if all(term in haystack for term in terms):
            matches.append(item)
            if len(matches) >= limit: break
    return matches
