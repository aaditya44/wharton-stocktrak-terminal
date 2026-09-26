#!/usr/bin/env python3
"""nightly_ml.py - self-contained nightly ML re-fit for GitHub Actions.

1. Extracts the committed bar baseline (data/bars_baseline.tar.gz) if present.
2. Best-effort incremental refresh: last 3mo daily bars from Yahoo's chart API
   (browser UA + cookie/crumb flow, 10 workers). Yahoo rate-limits datacenter
   IPs unpredictably; a failed refresh degrades to baseline bars + a warning,
   never to a dead pipeline.
3. Runs ml_rank.py twice (US-tradable + international), rebuilds the snapshot
   and the site. Bars are transient; only data outputs + index.html commit.
"""
import io, json, os, subprocess, sys, tarfile, time
import urllib.request, urllib.error, http.cookiejar
from concurrent.futures import ThreadPoolExecutor, as_completed

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
      "Accept": "application/json,text/plain,*/*"}

def barpath(sym):
    return os.path.join(DATA, f"bars_{sym.replace('^','I_').replace('=','_')}_1y.json")

def extract_baseline():
    tb = os.path.join(DATA, "bars_baseline.tar.gz")
    if not os.path.exists(tb):
        print("no baseline tarball; cold ingest only", flush=True)
        return 0
    n = 0
    with tarfile.open(tb, "r:gz") as t:
        for m in t:
            dst = os.path.join(DATA, os.path.basename(m.name))
            if m.isfile() and not os.path.exists(dst):
                with t.extractfile(m) as f, open(dst, "wb") as o:
                    o.write(f.read())
                n += 1
    print(f"baseline extracted: {n} bar files", flush=True)
    return n

_opener = None
def opener():
    global _opener
    if _opener is None:
        cj = http.cookiejar.CookieJar()
        _opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
        _opener.addheaders = list(UA.items())
        try:
            _opener.open("https://fc.yahoo.com", timeout=10)
        except Exception:
            pass
    return _opener

_crumb = None
def crumb():
    global _crumb
    if _crumb is None:
        try:
            _crumb = opener().open("https://query1.finance.yahoo.com/v1/test/getcrumb", timeout=15).read().decode().strip()
        except Exception:
            _crumb = ""
    return _crumb

ERRS = []
def fetch_recent(sym, tries=2):
    need = "2y"
    p = barpath(sym)
    if os.path.exists(p):
        try:
            if len(json.load(open(p))) >= 400:
                need = "3mo"
        except Exception:
            pass
    q = urllib.parse.quote(sym, safe="")
    for attempt in range(tries):
        host = "query1" if attempt == 0 else "query2"
        url = f"https://{host}.finance.yahoo.com/v8/finance/chart/{q}?range={need}&interval=1d&crumb={crumb()}"
        try:
            with opener().open(url, timeout=15) as r:
                j = json.loads(r.read())
            res = j["chart"]["result"][0]
            ts, qq = res["timestamp"], res["indicators"]["quote"][0]
            return [[t, o, c, v or 0] for t, o, c, v in zip(ts, qq["open"], qq["close"], qq["volume"]) if o and c]
        except Exception as e:
            if len(ERRS) < 3:
                ERRS.append(f"{sym}: {type(e).__name__} {e}")
            time.sleep(1.0)
    return None

def merge(sym, rows):
    p = barpath(sym)
    old = []
    if os.path.exists(p):
        try:
            old = json.load(open(p))
        except Exception:
            old = []
    by_t = {r[0]: r for r in old}
    for r in rows:
        by_t[r[0]] = r
    merged = [by_t[t] for t in sorted(by_t)]
    json.dump(merged, open(p, "w"))

def main():
    os.makedirs(DATA, exist_ok=True)
    extract_baseline()
    syms = [l.strip().split()[0] for l in open(os.path.join(HERE, "ml_universe.txt")) if l.strip()]
    have = sum(1 for s in syms if os.path.exists(barpath(s)))
    print(f"symbols={len(syms)} baseline coverage={have}", flush=True)

    ok = fail = 0
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=10) as ex:
        futs = {ex.submit(fetch_recent, s): s for s in syms}
        for i, f in enumerate(as_completed(futs)):
            rows = f.result()
            if rows:
                merge(futs[f], rows)
                ok += 1
            else:
                fail += 1
            if i % 200 == 199:
                print(f"{i+1}/{len(syms)} refreshed, ok={ok} fail={fail} ({time.time()-t0:.0f}s)", flush=True)
            if i == 299 and ok == 0:
                print("WARNING: 0/300 first fetches - Yahoo is blocking this runner; continuing on baseline bars", flush=True)
                for e in ERRS:
                    print("sample error:", e, flush=True)
                break
    print(f"refresh done: ok={ok} fail={fail} in {time.time()-t0:.0f}s", flush=True)
    have = sum(1 for s in syms if os.path.exists(barpath(s)))
    if have < int(0.8 * len(syms)):
        print(f"FATAL: bar coverage {have}/{len(syms)} below 80%", flush=True)
        sys.exit(1)

    env = dict(os.environ)
    env["ML_EVAL_EXCLUDE_SUFFIX"] = ".NS,.HK,.L,.TO,.DE,.PA,.MI,.MC,.AS,.BR"
    subprocess.run([sys.executable, os.path.join(HERE, "ml_rank.py")], env=env, check=True)
    env["ML_RANK_INTL"] = "1"
    subprocess.run([sys.executable, os.path.join(HERE, "ml_rank.py")], env=env, check=True)
    subprocess.run([sys.executable, os.path.join(HERE, "make_ml_snapshot.py")], check=True)
    subprocess.run([sys.executable, os.path.join(HERE, "build_site.py")], check=True)
    print("nightly re-fit complete", flush=True)

if __name__ == "__main__":
    main()
