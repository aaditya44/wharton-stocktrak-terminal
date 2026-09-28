#!/usr/bin/env python3
"""Hourly bar collector (Phase 0 of the intraday/self-learning upgrade).
Fetches 60m bars from Yahoo's chart API for the intraday universe
(current StockTrak holdings + top 100 US names of the latest unified ranking),
appends new closed bars to data/bars_hourly/<SYM>.json (deduped by timestamp).
Closed bars are fixed historical data, so a late-firing run just backfills.
"""
import json, os, sys, time, urllib.request, urllib.parse, http.cookiejar

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
      "Accept": "application/json"}
DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
OUT = os.path.join(DATA, "bars_hourly")
HOLDINGS = os.path.join(DATA, "holdings.txt")
RANK = os.path.join(DATA, "ml_ranking_intl.json")
TOP_N = 100
KEEP_BARS = 24 * 45  # ~45 trading days of hourly bars

_cj = http.cookiejar.CookieJar()
_opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(_cj))
_opener.addheaders = list(UA.items())
_crumb = None

def crumb():
    global _crumb
    if _crumb is None:
        try:
            _opener.open("https://query1.finance.yahoo.com/v1/test/getcrumb", timeout=15).read()
            _crumb = _opener.open("https://query1.finance.yahoo.com/v1/test/getcrumb", timeout=15).read().decode().strip()
        except Exception:
            _crumb = ""
    return _crumb

def universe():
    syms = []
    if os.path.exists(HOLDINGS):
        syms += [l.strip() for l in open(HOLDINGS) if l.strip() and not l.startswith("#")]
    try:
        rows = json.load(open(RANK))
        if isinstance(rows, dict):
            rows = rows.get("rows") or rows.get("data") or []
        us = [r for r in rows if "." not in r.get("symbol", "")]
        us.sort(key=lambda r: -(r.get("blend") or r.get("ml") or 0))
        syms += [r["symbol"] for r in us[:TOP_N]]
    except Exception as e:
        print("ranking read failed:", e)
    seen, out = set(), []
    for s in syms:
        if s not in seen:
            seen.add(s); out.append(s)
    return out

def fetch(sym):
    q = urllib.parse.quote(sym)
    for attempt in range(2):
        host = "query1" if attempt == 0 else "query2"
        url = f"https://{host}.finance.yahoo.com/v8/finance/chart/{q}?range=5d&interval=60m&includePrePost=false&crumb={urllib.parse.quote(crumb())}"
        try:
            j = json.loads(_opener.open(url, timeout=20).read().decode())
            res = j["chart"]["result"][0]
            ts = res.get("timestamp") or []
            qt = res["indicators"]["quote"][0]
            bars = []
            for i, t in enumerate(ts):
                c = qt["close"][i]
                if c is None:
                    continue
                bars.append({"t": int(t),
                             "o": qt["open"][i], "h": qt["high"][i],
                             "l": qt["low"][i], "c": c,
                             "v": qt["volume"][i] or 0})
            return bars
        except Exception as e:
            if attempt == 1:
                print(f"  {sym}: FAIL {e}")
            time.sleep(1.5)
    return None

def main():
    os.makedirs(OUT, exist_ok=True)
    syms = universe()
    print(f"intraday universe: {len(syms)} symbols")
    updated = failed = 0
    pending = list(syms)
    for rnd in range(3):  # Yahoo 429s are window-based; wait and retry failures
        if rnd:
            print(f"round {rnd+1}: {len(pending)} pending, waiting 75s")
            time.sleep(75)
        nxt = []
        for k, sym in enumerate(pending):
            bars = fetch(sym)
            if bars is None:
                nxt.append(sym)
                continue
        path = os.path.join(OUT, f"{sym}.json")
        old = {}
        if os.path.exists(path):
            try:
                old = {b["t"]: b for b in json.load(open(path)).get("bars", [])}
            except Exception:
                old = {}
        for b in bars:
            old[b["t"]] = b
        merged = sorted(old.values(), key=lambda b: b["t"])[-KEEP_BARS:]
        json.dump({"symbol": sym, "interval": "60m",
                   "updated_utc": int(time.time()), "bars": merged}, open(path, "w"))
            updated += 1
            if k % 20 == 19:
                print(f"  round {rnd+1}: {k+1}/{len(pending)} done")
            time.sleep(1.2)
        pending = nxt
        if not pending:
            break
    failed = len(pending)
    print(f"updated={updated} failed={failed}")

if __name__ == "__main__":
    main()
