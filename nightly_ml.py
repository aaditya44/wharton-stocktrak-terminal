#!/usr/bin/env python3
"""nightly_ml.py - self-contained nightly ML re-fit for GitHub Actions.

1. Refreshes 2y daily bars for ml_universe.txt symbols from the Yahoo chart API
   (plain HTTPS, no browser, polite 250ms spacing).
2. Runs ml_rank.py twice (US-tradable ranking + international ranking).
3. Rebuilds data/ml_snapshot.json and index.html.
Bars are transient (not committed); only snapshot/validation/site outputs commit.
"""
import json, os, subprocess, sys, time, urllib.request, urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")

def fetch_bars(sym, tries=2):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(sym, safe='')}?range=2y&interval=1d"
    for _ in range(tries):
        try:
            with urllib.request.urlopen(url, timeout=20) as r:
                j = json.loads(r.read())
            res = j["chart"]["result"][0]
            ts, q = res["timestamp"], res["indicators"]["quote"][0]
            rows = [[t, o, c, v or 0] for t, o, c, v in zip(ts, q["open"], q["close"], q["volume"]) if o and c]
            return rows if len(rows) > 300 else None
        except Exception:
            time.sleep(1.5)
    return None

def main():
    syms = [l.strip().split()[0] for l in open(os.path.join(HERE, "ml_universe.txt")) if l.strip()]
    ok = 0
    for i, s in enumerate(syms):
        rows = fetch_bars(s)
        if rows:
            json.dump(rows, open(os.path.join(DATA, f"bars_{s.replace('^','I_').replace('=','_')}_1y.json"), "w"))
            ok += 1
        if i % 100 == 99:
            print(f"{i+1}/{len(syms)} ingested, ok={ok}", flush=True)
        time.sleep(0.25)
    print(f"ingest done: {ok}/{len(syms)}")
    env = dict(os.environ)
    env["ML_EVAL_EXCLUDE_SUFFIX"] = ".NS,.HK,.L,.TO,.DE,.PA,.MI,.MC,.AS,.BR"
    subprocess.run([sys.executable, os.path.join(HERE, "ml_rank.py")], env=env, check=True)
    env["ML_RANK_INTL"] = "1"
    subprocess.run([sys.executable, os.path.join(HERE, "ml_rank.py")], env=env, check=True)
    subprocess.run([sys.executable, os.path.join(HERE, "make_ml_snapshot.py")], check=True)
    subprocess.run([sys.executable, os.path.join(HERE, "build_site.py")], check=True)

if __name__ == "__main__":
    main()
