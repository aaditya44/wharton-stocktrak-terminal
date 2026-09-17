#!/usr/bin/env python3
"""StockTrak research prototype v0.1 - overnight vs intraday return decomposition.

Data path verified 2026-09-18: tools web_fetch on the Yahoo Finance chart API.
Known constraint: fetch success is per-symbol (today AAPL/NVDA/SPY/^GSPC/GC=F/CL=F
work; several ETFs return CRAWL_UNEXPECTED_CONTENT_TYPE). The script treats a
failed symbol as SKIP, never as an error that stops the run, and caches every
good pull to data/bars_<symbol>.json so history is never re-fetched.

Usage: python3 overnight_decomp.py [range]   (range: 6mo|1y|2y, default 1y)
Output: console stats + data/decomp_<range>.csv
"""
import json, math, os, statistics, subprocess, sys, time, urllib.parse, csv

UNIVERSE = ["AAPL", "NVDA", "SPY", "^GSPC", "GC=F", "CL=F"]  # verified 2026-09-18
DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
os.makedirs(DATA, exist_ok=True)

def fetch_daily(symbol, rng):
    cache = os.path.join(DATA, f"bars_{symbol.replace('^','I_').replace('=','_')}_{rng}.json")
    if os.path.exists(cache):
        rows = json.load(open(cache))
        if rows: return rows, "cache"
    enc = urllib.parse.quote(symbol, safe="")
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{enc}?range={rng}&interval=1d"
    for attempt in range(3):
        out = subprocess.run(["tools", "web_fetch", "--url", url],
                             capture_output=True, text=True, timeout=120).stdout
        body = next((l.strip() for l in out.splitlines() if l.strip().startswith('{"chart"')), None)
        if body:
            res = json.loads(body)["chart"]["result"][0]
            q = res["indicators"]["quote"][0]
            rows = [(t, o, c) for t, o, c in zip(res["timestamp"], q["open"], q["close"]) if o and c]
            json.dump(rows, open(cache, "w"))
            return rows, "live"
        time.sleep(3)
    return None, "skip"

def decompose(rows):
    on, intra = [], []
    for i in range(1, len(rows)):
        pc, o, c = rows[i-1][2], rows[i][1], rows[i][2]
        on.append(math.log(o / pc)); intra.append(math.log(c / o))
    return on, intra

def stats(xs):
    if len(xs) < 30: return None
    mean = statistics.mean(xs) * 252 * 100
    vol = statistics.pstdev(xs) * math.sqrt(252) * 100
    return dict(n=len(xs), ann_mean=round(mean,1), ann_vol=round(vol,1),
                sharpe=round(mean/vol,2) if vol else None,
                hit=round(sum(1 for x in xs if x>0)/len(xs)*100))

def main():
    rng = sys.argv[1] if len(sys.argv) > 1 else "1y"
    out_rows = []
    for s in UNIVERSE:
        rows, src = fetch_daily(s, rng)
        if not rows:
            print(f"{s:>6}: SKIP (fetch blocked for this symbol today)")
            continue
        on, intra = decompose(rows)
        so, si = stats(on), stats(intra)
        print(f"{s:>6} [{src}, n={len(rows)} bars]")
        for label, st in (("overnight", so), ("intraday", si)):
            if st:
                print(f"        {label}: ann.mean={st['ann_mean']:+.1f}%  ann.vol={st['ann_vol']}%  "
                      f"sharpe={st['sharpe']:+.2f}  hit={st['hit']}%")
                out_rows.append([s, rng, label, st["n"], st["ann_mean"], st["ann_vol"], st["sharpe"], st["hit"]])
    csv_path = os.path.join(DATA, f"decomp_{rng}.csv")
    with open(csv_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["symbol","range","component","n","ann_mean_pct","ann_vol_pct","sharpe","hit_pct"])
        w.writerows(out_rows)
    print(f"\nwrote {csv_path} ({len(out_rows)} rows)")

if __name__ == "__main__":
    main()
