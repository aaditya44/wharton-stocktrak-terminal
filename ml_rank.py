#!/usr/bin/env python3
"""ml_rank.py - learned factor weights via walk-forward cross-sectional ridge.

Same factor set as engine.py (explainable) + 2 regime interactions.
Per date: z-score features & forward-21d-return cross-sectionally.
Train ridge on expanding window, embargo = horizon (purged).
Regime enters as interactions (raw regime is constant per date -> z kills it).

Outputs (in data/):
  ml_weights_history.json  - learned weights per OOS date
  ml_ranking.json          - latest ml_score, blend, per-factor contributions
  ml_validation.json       - OOS IC: ML vs fixed baseline, blend decision
"""
import json, math, os, glob
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ST = os.path.dirname(HERE)
DATA = os.path.join(ST, "data")
HOR = int(os.environ.get("ML_HOR", "21"))
MINHIST = 130
LAM = float(os.environ.get("ML_LAM", "10"))
OOS_START = 80
FEATS = ["ret_3m","ret_1m","on_sharpe","vol20","trend","hi52",
         "ret3m_x_spyvol","vol20_x_spyret"]
FIXED_W = np.array([0.30,0.15,0.15,-0.15,0.15,0.10,0.0,0.0])

def load_bars(sym):
    p = os.path.join(DATA, f"bars_{sym}_1y.json")
    if not os.path.exists(p): return None
    try: a = np.array(json.load(open(p)), dtype=float)
    except Exception: return None
    return a if len(a) >= MINHIST + HOR + 5 else None

def factor_panel(a):
    op, cl = a[:,1], a[:,2]
    n = len(cl); T = n - MINHIST
    lr = np.diff(np.log(cl))
    F = np.full((T,6), np.nan)
    for j in range(T):
        t = MINHIST + j
        c = cl[:t+1]
        F[j,0] = (c[-1]/c[-64]-1)*100
        F[j,1] = (c[-1]/c[-22]-1)*100
        on = np.log(op[1:t+1]/cl[:t])
        sd = on.std()
        F[j,2] = (on.mean()*252)/(sd*math.sqrt(252)) if sd>0 else 0.0
        F[j,3] = lr[max(0,t-20):t].std()*math.sqrt(252)*100
        ma50 = c[-50:].mean()
        F[j,4] = (c[-63:]>ma50).mean()*100
        F[j,5] = c[-1]/c.max()*100
    return (a[MINHIST:,0] // 86400).astype(int), F  # UTC-day keys: aligns exchange-local epochs across markets

def zc(x):
    x = np.asarray(x, float)
    s = x.std()
    return (x - x.mean())/(s if s>0 else 1.0)

def main():
    syms = sorted(os.path.basename(p)[5:-8] for p in glob.glob(os.path.join(DATA,"bars_*_1y.json")))
    spy = load_bars("SPY")
    spy_map = {}
    if spy is not None:
        sd_, sF = factor_panel(spy)
        sv = zc(sF[:,3]); sr = zc(sF[:,1])  # time-series z of spy vol / ret
        spy_map = {int(d): (float(sv[i]), float(sr[i])) for i,d in enumerate(sd_)}
    # per-date sample store: date -> (syms, Xraw[n,6], y[n])
    by_date = {}
    nloaded = 0
    for s in syms:
        a = load_bars(s)
        if a is None: continue
        tail = a[-20:,2]
        if tail[-1] < 5.0 or float(tail.std()) == 0.0: continue  # sub-$5 or frozen/halted
        ds, F = factor_panel(a)
        cl = a[:,2]
        ok = ~np.isnan(F).any(axis=1)
        idx = np.where(ok)[0]
        nloaded += 1
        for j in idx:
            t = MINHIST + j
            if t+HOR >= len(cl): y = np.nan
            else: y = (cl[t+HOR]/cl[t]-1)*100
            d = int(ds[j])
            e = by_date.setdefault(d, [[],[],[]])
            e[0].append(s); e[1].append(F[j]); e[2].append(y)
    dates = sorted(by_date)
    print(f"panels={nloaded} dates={len(dates)} range={dates[0]}..{dates[-1]}")
    dpos = {d:i for i,d in enumerate(dates)}
    # per-date z-scored design, gram matrices
    gramS, gramb, dateIC_fixed, dateIC_syml, samples = {}, {}, {}, {}, {}
    Xz_by_date, yz_by_date = {}, {}
    for d in dates:
        syml, Xl, yl = by_date[d]
        X = np.array(Xl); y = np.array(yl)
        spyv, spyr = spy_map.get(d, (0.0,0.0))
        i1 = X[:,0]*spyv           # ret_3m x spy vol z
        i2 = X[:,3]*spyr           # vol20 x spy ret z
        X8 = np.column_stack([X, i1, i2])
        Xz = np.apply_along_axis(zc, 0, X8)
        m = ~np.isnan(y)
        yz = np.where(m, zc(np.where(m,y,0)), np.nan)
        Xz_by_date[d] = (syml, Xz); yz_by_date[d] = yz
        if m.sum() > 200:
            Xm = Xz[m]; ym = yz[m]
            gramS[d] = Xm.T@Xm; gramb[d] = Xm.T@ym
            fs = Xm[:,:6]@FIXED_W[:6]
            dateIC_fixed[d] = float(np.corrcoef(zc(fs), ym)[0,1])
            dateIC_syml[d] = syml  # keep for masked re-eval
    # walk-forward
    oos = [d for d in dates if dpos[d] >= OOS_START and d in gramS]
    ic_ml, ic_fx, weights_hist = [], [], []
    blend_ic = {}
    S = np.zeros((8,8)); b = np.zeros(8)
    train_dates = []
    for d in oos:
        di = dpos[d]
        # add newly matured dates (embargo: date index <= di-HOR-1)
        while train_dates and dpos[train_dates[0]] <= di-HOR-1 or (not train_dates):
            break
        # rebuild cumulative gram lazily: keep pointer
        matured = [dd for dd in dates if dpos[dd] <= di-HOR-1 and dd in gramS]
        S = sum((gramS[dd] for dd in matured), np.zeros((8,8)))
        b = sum((gramb[dd] for dd in matured), np.zeros(8))
        w = np.linalg.solve(S + LAM*np.eye(8), b)
        syml, Xz = Xz_by_date[d]; yz = yz_by_date[d]
        m = ~np.isnan(yz)
        excl = [x for x in os.environ.get("ML_EVAL_EXCLUDE_SUFFIX", "").split(",") if x]
        if excl:
            keep = np.array([not any(s.endswith(x) for x in excl) for s in syml])
            m = m & keep
        if m.sum() < 50:
            continue  # foreign-only trading day (US holiday): nothing to evaluate
        pred = Xz[m]@w
        ic = float(np.corrcoef(zc(pred), yz[m])[0,1])
        fz_t = zc(Xz[m][:,:6]@FIXED_W[:6]); pz = zc(pred)
        for wB in (0.0,0.25,0.5,0.75,1.0):
            blend_ic.setdefault(wB,[]).append(float(np.corrcoef(wB*pz+(1-wB)*fz_t, yz[m])[0,1]))
        ic_ml.append(ic)
        if excl:
            syml2 = syml
            keep2 = np.array([not any(s.endswith(x) for x in excl) for s in syml2])
            fm = keep2 & ~np.isnan(yz)
            fs2 = Xz[fm][:,:6]@FIXED_W[:6]
            ic_fx.append(float(np.corrcoef(zc(fs2), yz[fm])[0,1]))
        else:
            ic_fx.append(dateIC_fixed[d])
        weights_hist.append(dict(date=int(d), n_train=int(len(matured)*1400),
            **{f: round(float(wi),3) for f,wi in zip(FEATS,w)}, ic=round(ic,3),
            ic_fixed=round(dateIC_fixed[d],3)))
    ic_ml = np.array(ic_ml); ic_fx = np.array(ic_fx)
    ic_fx = np.where(np.isnan(ic_fx), ic_ml, ic_fx)  # masked dates fallback
    val = dict(
        oos_dates=len(oos), horizon=HOR, lam=LAM, feats=FEATS,
        ic_ml_mean=round(float(ic_ml.mean()),4), ic_ml_std=round(float(ic_ml.std()),4),
        ic_fixed_mean=round(float(ic_fx.mean()),4), ic_fixed_std=round(float(ic_fx.std()),4),
        ic_ml_tstat=round(float(ic_ml.mean()/(ic_ml.std()/math.sqrt(len(ic_ml)) or 1)),2),
        ic_fixed_tstat=round(float(ic_fx.mean()/(ic_fx.std()/math.sqrt(len(ic_fx)) or 1)),2),
        blend_curve={str(k): round(float(np.mean(v)),4) for k,v in sorted(blend_ic.items())},
        blend_halves={str(k): [round(float(np.mean(v[:len(v)//2])),4), round(float(np.mean(v[len(v)//2:])),4)] for k,v in sorted(blend_ic.items())},
        ml_beats_fixed=bool(ic_ml.mean() > ic_fx.mean()),
        blend_note="blend 50/50 only if ml_beats_fixed else pure fixed tracker")
    json.dump(val, open(os.path.join(DATA,"ml_validation.json"),"w"), indent=1)
    json.dump(weights_hist, open(os.path.join(DATA,"ml_weights_history.json"),"w"), indent=1)
    # latest-date ranking with per-name contributions
    d = dates[-1]
    # stale-symbol inclusion: symbols whose latest bar is 1-3 days behind the ranking
    # date (exchange holiday / missed ingest) still rank, scored on their own latest
    # features standardized against the ranking-date cross-section.
    STALE_MAX = 3
    matured = [dd for dd in dates if dpos[dd] <= dpos[d]-HOR-1 and dd in gramS]
    S = sum((gramS[dd] for dd in matured), np.zeros((8,8)))
    b = sum((gramb[dd] for dd in matured), np.zeros(8))
    w = np.linalg.solve(S + LAM*np.eye(8), b)
    syml, Xz = Xz_by_date[d]
    # ranking-date standardization stats (rebuilt on the 8-col design)
    syml_d, Xl_d, _ = by_date[d]
    X_d = np.array(Xl_d); spyv_d, spyr_d = spy_map.get(d, (0.0,0.0))
    X8_d = np.column_stack([X_d, X_d[:,0]*spyv_d, X_d[:,3]*spyr_d])
    mu_d, sd_d = X8_d.mean(axis=0), X8_d.std(axis=0); sd_d[sd_d==0]=1.0
    extra = []  # (symbol, Xz row, staleness)
    seen = set(syml)
    for dd in dates[-(STALE_MAX+1):-1][::-1]:
        syl, Xl2, _ = by_date[dd]
        spyv_s, spyr_s = spy_map.get(dd, (0.0,0.0))
        for s2, xr in zip(syl, Xl2):
            if s2 in seen: continue
            seen.add(s2)
            x8 = np.concatenate([xr, [xr[0]*spyv_s, xr[3]*spyr_s]])
            extra.append((s2, (x8-mu_d)/sd_d, int(d-dd)))
    if extra:
        syml = syml + [e[0] for e in extra]
        Xz = np.vstack([Xz, np.array([e[1] for e in extra])])
        print(f"stale-filled: {len(extra)} symbols on 1-{STALE_MAX}d-old bars")
    stale_of = {e[0]: e[2] for e in extra}
    ml = Xz@w; fx = Xz[:,:6]@FIXED_W[:6]
    WB = float(os.environ.get("ML_BLEND", "0.5"))
    if val["ml_beats_fixed"]:
        blend = WB*zc(ml)+(1-WB)*zc(fx); mode=f"blend{int(WB*100)}"  # 0.75 split-half favored (H2 IC rises with ML weight); default 0.5 until user signs off on the bigger turnover
    else:
        blend = zc(fx); mode="fixed_fallback"
    contrib = Xz*w
    rows = []
    for i,s in enumerate(syml):
        if not os.environ.get("ML_RANK_INTL") and s.endswith((".NS",".L",".HK",".TO",".DE",".PA",".MI",".MC",".AS",".BR")): continue  # training pool only; default ranking is US-tradable
        rows.append(dict(symbol=s, stale=stale_of.get(s,0), ml=round(float(zc(ml)[i]),3),
                         fixed=round(float(zc(fx)[i]),3),
                         blend=round(float(blend[i]),3),
                         top_contrib=sorted(zip(FEATS, [round(float(c),2) for c in contrib[i]]),
                                            key=lambda kv:-abs(kv[1]))[:3]))
    rows.sort(key=lambda r:-r["blend"])
    if os.environ.get("ML_RANK_INTL"):
        outname = "ml_ranking_intl.json"
    else:
        outname = "ml_ranking.json" if WB==0.5 else f"ml_ranking_b{int(WB*100)}.json"
    json.dump(dict(date=int(d), mode=mode, weights={f:round(float(wi),3) for f,wi in zip(FEATS,w)},
                   rows=rows), open(os.path.join(DATA,outname),"w"), indent=1)
    print(json.dumps(val, indent=1))
    print("mode:", mode, "weights:", {f:round(float(wi),3) for f,wi in zip(FEATS,w)})
    print("top10:", [r["symbol"] for r in rows[:10]])

if __name__ == "__main__":
    main()
