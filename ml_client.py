# ml_client.py - RECONSTRUCTED 2026-09-27 after workspace wipe, from the documented spec:
# vol-band mult (<=25%: 1.0, <=37.5%: 0.6, else 0.2), $5M median daily-$-volume floor,
# price >= $5, leveraged ETFs held out of the growth list (5% IPS slot), event-risk set excluded,
# HCWC excluded upstream. Universe: US ONLY - the Wharton StockTrak account trades North America / US exchange only (parent directive 2026-09-30 after the .L anomaly: London names untradeable and pence-priced).
import json, math, os, glob
import numpy as np
DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
EVENT_RISK = {"MRNA","NVAX","SRPT","BNTX","GME","MARA","CLSK","COIN","HOOD"}
# Hormuz-escalation guardrail (parent directive Sun 6:34pm): cap energy at 3 of 12 core names.
# Heuristic GICS-energy set - bars carry no sector field, so named tickers only; flagged in briefs.
ENERGY = {"CVI","DINO","VLO","MPC","LPG","XOM","CVX","COP","EOG","OXY","SLB","HAL","BKR","PSX",
          "HES","DVN","FANG","CTRA","EQT","WMB","KMI","OKE","TRGP","LNG","MRO","APA","BP","SHEL","TTE"}
MAX_ENERGY = 3
LEVERAGED = {"SOXL","SOXS","TQQQ","SQQQ","UPRO","SPXU","TNA","TZA","UVXY","SVXY","LABU","LABD",
             "FAS","FAZ","NVDL","TSLL","MSTX","CONL","YINN","YANG","WEBL","WEBS","TECL","TECS",
             "DRN","DRV","URTY","SRTY","TMF","TMV","UDOW","SDOW","UWM","TWM","BITX","BITU"}
def bars(sym):
    p = os.path.join(DATA, f"bars_{sym}_1y.json")
    if not os.path.exists(p): return None
    try: return np.array(json.load(open(p)), dtype=float)
    except Exception: return None
def screen(sym):
    if "." in sym: return None, "non-US (account trades US exchange only)"
    a = bars(sym)
    if a is None or len(a) < 60: return None, "no bars"
    cl, vol = a[:,2], a[:,3]
    last = cl[-1]
    if last < 5: return None, f"price {last:.2f}<5"
    dvol = float(np.median((cl*vol)[-20:]))
    if dvol < 5e6: return None, f"$vol {dvol/1e6:.1f}M<5M"
    v20 = float(np.diff(np.log(cl))[-20:].std()*math.sqrt(252)*100)
    mult = 1.0 if v20 <= 25 else (0.6 if v20 <= 37.5 else 0.2)
    return dict(last=last, v20=v20, dvol=dvol, mult=mult), "ok"
def main():
    d = json.load(open(os.path.join(DATA, "ml_ranking_intl.json")))
    rows = d.get("ranking") or d.get("rows")
    picks, skipped = [], []
    for r in rows:
        s = r["symbol"]
        if s in EVENT_RISK: skipped.append((s,"event-risk")); continue
        if s in LEVERAGED: skipped.append((s,"leveraged->5% slot")); continue
        if s in ENERGY and sum(1 for p in picks if p["symbol"] in ENERGY) >= MAX_ENERGY:
            skipped.append((s,"energy cap 3")); continue
        info, why = screen(s)
        if info is None: skipped.append((s,why)); continue
        if info["mult"] < 0.6:
            skipped.append((s, f"vol {info['v20']:.0f}%>37.5% (0.2 band: not core-sleeve suitable)")); continue
        picks.append(dict(symbol=s, rank=len(picks)+len([1]), model_rank=rows.index(r)+1, **info))
        if len(picks) >= 12: break
    GROWTH = 170000.0
    per = GROWTH/len(picks)
    picks = [p for p in picks if per*p["mult"]//p["last"] >= 1]  # zero-share guard
    for p in picks:
        p["dollars"] = round(per*p["mult"], 0)
        p["shares"] = int(p["dollars"]//p["last"])
    print(f"{'sym':7}{'mrank':>6}{'last':>9}{'v20':>6}{'$volM':>7}{'mult':>5}{'shares':>8}{'$$':>9}")
    for p in picks:
        print(f"{p['symbol']:7}{p['model_rank']:>6}{p['last']:>9.2f}{p['v20']:>6.1f}{p['dvol']/1e6:>7.0f}{p['mult']:>5}{p['shares']:>8}{p['dollars']:>9.0f}")
    json.dump(dict(source="ml_ranking_intl.json "+str(d.get("date")), growth=GROWTH, picks=picks,
                   skipped_top=skipped[:30]), open("/home/sandbox/st/docs/ml_client_regen.json","w"), indent=1)
if __name__ == "__main__": main()
