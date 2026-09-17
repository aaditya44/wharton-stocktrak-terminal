#!/usr/bin/env python3
"""ingest.py - fetch the next batch of uncached universe symbols (polite, small batches)."""
import json, os, subprocess, sys, time, urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
BATCH = int(sys.argv[1]) if len(sys.argv) > 1 else 5

def cache_path(sym):
    return os.path.join(DATA, f"bars_{sym.replace('^','I_').replace('=','_')}_1y.json")

todo = []
for line in open(os.path.join(HERE, "universe.txt")):
    parts = line.split()
    if not parts: continue
    sym = parts[0]
    if not os.path.exists(cache_path(sym)):
        todo.append(sym)

print(f"{len(todo)} symbols still uncached")
done = 0
attempted = 0
for sym in todo:
    if done >= BATCH or attempted >= BATCH + 2: break
    attempted += 1
    enc = urllib.parse.quote(sym, safe="")
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{enc}?range=1y&interval=1d"
    ok = False
    for attempt in range(2):
        out = subprocess.run(["tools", "web_fetch", "--url", url, "--timeout", "20"],
                             capture_output=True, text=True, timeout=30).stdout
        body = next((l.strip() for l in out.splitlines() if l.strip().startswith('{"chart"')), None)
        if body:
            res = json.loads(body)["chart"]["result"][0]
            q = res["indicators"]["quote"][0]
            rows = [(t, o, c) for t, o, c in zip(res["timestamp"], q["open"], q["close"]) if o and c]
            if len(rows) > 50:
                json.dump(rows, open(cache_path(sym), "w"))
                print(f"{sym}: cached {len(rows)} bars"); ok = True; done += 1
                break
        time.sleep(2)
    if not ok:
        print(f"{sym}: blocked this round")
    time.sleep(3)  # polite spacing between symbols
