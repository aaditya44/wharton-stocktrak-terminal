#!/usr/bin/env python3
"""make_ml_snapshot.py - convert ML artifacts into data/ml_snapshot.json for the site.

Reads: data/ml_ranking.json (US, unified single-model), data/ml_ranking_intl.json (all markets),
       data/ml_validation.json, data/ml_weights_history.json (latest learned weights)
Writes: data/ml_snapshot.json - picks, scores, learned weights, plain-English why.
"""
import json, os, datetime as dt

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")

FEAT_EN = {
 "ret_3m": ("3-month momentum", "how much the stock rose over the last 3 months"),
 "ret_1m": ("1-month momentum", "how much the stock rose over the last month"),
 "on_sharpe": ("overnight quality", "consistency of overnight (close-to-open) returns"),
 "vol20": ("20-day volatility", "how jumpy the stock has been over the last month"),
 "trend": ("trend consistency", "share of recent days spent above the 50-day average"),
 "hi52": ("52-week-high distance", "how close the price is to its 52-week high"),
 "ret3m_x_spyvol": ("momentum x market fear", "3-month momentum scaled by market volatility"),
 "vol20_x_spyret": ("vol x market direction", "own volatility scaled by recent market return"),
}

def why(row):
    parts = []
    for f, c in row.get("top_contrib", [])[:3]:
        name, plain = FEAT_EN.get(f, (f, f))
        parts.append(f"{name} {'helps' if c > 0 else 'drags'} ({c:+.2f})")
    return "; ".join(parts)

def main():
    rank = json.load(open(os.path.join(DATA, "ml_ranking.json")))
    val = json.load(open(os.path.join(DATA, "ml_validation.json")))
    hist = json.load(open(os.path.join(DATA, "ml_weights_history.json")))
    latest_w = hist[-1] if hist else {}
    weights = []
    for f in ["ret_3m","ret_1m","on_sharpe","vol20","trend","hi52","ret3m_x_spyvol","vol20_x_spyret"]:
        name, plain = FEAT_EN[f]
        weights.append(dict(factor=f, name=name, plain=plain, weight=latest_w.get(f, 0.0)))
    picks = []
    for r in rank["rows"][:15]:
        picks.append(dict(symbol=r["symbol"], model=r["blend"], benchmark=r["fixed"], stale=r.get("stale",0), why=why(r)))
    intl = []
    ipath = os.path.join(DATA, "ml_ranking_intl.json")
    if os.path.exists(ipath):
        irank = json.load(open(ipath))
        seen = 0
        for r in irank["rows"]:
            if r["symbol"].endswith((".NS",".HK",".L",".TO",".DE",".PA",".MI",".MC",".AS",".BR")):
                intl.append(dict(symbol=r["symbol"], model=r["blend"], stale=r.get("stale",0), why=why(r)))
                seen += 1
            if seen >= 10: break
    snap = dict(
        date=dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        mode=rank.get("mode","unified"),
        weights=weights,
        picks=picks, intl_picks=intl,
        validation=dict(
            oos_days=val.get("oos_dates"), ic_ml=val.get("ic_ml_mean"), ic_fixed=val.get("ic_fixed_mean"),
            tstat=val.get("ic_ml_tstat"), blend_curve=val.get("blend_curve")),
        note="Walk-forward ridge, 21-day horizon, purged training; re-fits nightly.",
    )
    out = os.path.join(DATA, "ml_snapshot.json")
    json.dump(snap, open(out, "w"), indent=1)
    print("wrote", out, f"picks={len(picks)} intl={len(intl)}")

if __name__ == "__main__":
    main()
