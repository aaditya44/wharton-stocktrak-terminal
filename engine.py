#!/usr/bin/env python3
"""engine.py - explainable cross-sectional buy/sell ranking engine.

Factors per symbol (all from 1y daily bars):
  ret_1m, ret_3m   : trailing % returns (21/63 bars)
  vol20            : 20d realized vol, annualized %
  on_sharpe        : overnight (close->open) log-return Sharpe, annualized
  trend            : % of last 63 closes above the 50d mean
  hi52             : last close / 52w max close

Composite = fixed a-priori weighted z-scores (NO fitted parameters):
  0.30*z(ret_3m) + 0.15*z(ret_1m) + 0.15*z(on_sharpe)
  + 0.15*z(-vol20) + 0.15*z(trend) + 0.10*z(hi52)

Every row exposes raw factor values AND each factor's z-contribution,
so the rank is fully explainable. Output: data/ranking.json
"""
import json, math, os, statistics

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
WEIGHTS = {"ret_3m": 0.30, "ret_1m": 0.15, "on_sharpe": 0.15,
           "low_vol": 0.15, "trend": 0.15, "hi52": 0.10}

def cache_path(sym):
    return os.path.join(DATA, f"bars_{sym.replace('^','I_').replace('=','_')}_1y.json")

def factors(sym, rows):
    closes = [r[2] for r in rows]
    if len(closes) < 130: return None
    rets = [math.log(closes[i]/closes[i-1]) for i in range(1, len(closes))]
    last = closes[-1]
    ret_1m = (closes[-1]/closes[-22]-1)*100 if len(closes) > 22 else None
    ret_3m = (closes[-1]/closes[-64]-1)*100 if len(closes) > 64 else None
    v20 = rets[-20:]
    vol20 = statistics.pstdev(v20)*math.sqrt(252)*100
    on = [math.log(rows[i][1]/rows[i-1][2]) for i in range(1, len(rows))]
    om, ov = statistics.mean(on)*252, statistics.pstdev(on)*math.sqrt(252)
    on_sharpe = om/ov if ov else 0.0
    ma50 = statistics.mean(closes[-50:])
    trend = sum(1 for c in closes[-63:] if c > ma50)/63*100
    hi52 = last/max(closes)*100
    return dict(symbol=sym, n=len(closes), close=round(last, 2),
                ret_1m=round(ret_1m, 1), ret_3m=round(ret_3m, 1),
                vol20=round(vol20, 1), on_sharpe=round(on_sharpe, 2),
                trend=round(trend), hi52=round(hi52, 1))

def zscores(rows, key):
    xs = [r[key] for r in rows]
    mu, sd = statistics.mean(xs), statistics.pstdev(xs)
    return {id(r): (r[key]-mu)/sd if sd else 0.0 for r in rows}

def compute():
    universe = {}
    for line in open(os.path.join(HERE, "universe.txt")):
        p = line.split()
        if p: universe[p[0]] = p[1]
    rows = []
    for sym, sector in universe.items():
        cp = cache_path(sym)
        if not os.path.exists(cp): continue
        f = factors(sym, json.load(open(cp)))
        if f:
            f["sector"] = sector
            rows.append(f)
    if not rows: return []
    zmap = {k: zscores(rows, k) for k in ["ret_3m", "ret_1m", "on_sharpe", "vol20", "trend", "hi52"]}
    for r in rows:
        contrib = {
            "ret_3m":  WEIGHTS["ret_3m"]   * zmap["ret_3m"][id(r)],
            "ret_1m":  WEIGHTS["ret_1m"]   * zmap["ret_1m"][id(r)],
            "on_sharpe":WEIGHTS["on_sharpe"]* zmap["on_sharpe"][id(r)],
            "low_vol": WEIGHTS["low_vol"]  * (-zmap["vol20"][id(r)]),
            "trend":   WEIGHTS["trend"]    * zmap["trend"][id(r)],
            "hi52":    WEIGHTS["hi52"]     * zmap["hi52"][id(r)],
        }
        r["contrib"] = {k: round(v, 3) for k, v in contrib.items()}
        r["score"] = round(sum(contrib.values()), 3)
    rows.sort(key=lambda r: -r["score"])
    n = len(rows)
    for i, r in enumerate(rows):
        r["rank"] = i+1
        r["signal"] = "BUY" if i < max(1, n//4) else ("AVOID" if i >= n - max(1, n//4) else "WATCH")
        r["confidence"] = "full" if r["n"] >= 240 else "partial"
    json.dump(rows, open(os.path.join(DATA, "ranking.json"), "w"), indent=1)
    return rows

if __name__ == "__main__":
    rows = compute()
    print(f"{len(rows)} symbols ranked")
    for r in rows[:10]:
        print(f"  #{r['rank']} {r['symbol']:>6} {r['sector']:<12} score={r['score']:+.3f} "
              f"3m={r['ret_3m']:+.1f}% vol={r['vol20']}% onSharpe={r['on_sharpe']:+.2f} -> {r['signal']}")
