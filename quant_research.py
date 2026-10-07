#!/usr/bin/env python3
"""Offline research utilities. No network, broker, order or publication calls.

python quant_research.py self-test
python quant_research.py import-csv input.csv --out-dir /private/history
python quant_research.py shadow signals.json --data-dir /private/history --fee 25 --slippage-bps 10 --output /private/result.json

CSV: symbol,date,open,close,volume (UTC dates; consistently adjusted prices).
Import defaults to validation only. --write requires --rights-confirmed; that
flag records the operator's decision, it does not verify a vendor license.
Use a private directory. Importing never makes data public or clears rights.
Signals: [{"as_of":"YYYY-MM-DD","weights":{"SPY":0.5}}]. Must be
frozen before the following session opens. Remaining weight stays in cash.
Shadow simulation is a mechanical test, not evidence of profitable trading.
Universe survivorship, dividends, point-in-time availability and market impact
are not modelled. Fractional shares; long-only; no leverage or shorting.
"""
import argparse, csv, json, math, os, re, tempfile, unittest
from datetime import datetime, timezone
from pathlib import Path

SYMBOL = re.compile(r'^[A-Z0-9][A-Z0-9.^_-]{0,29}$')
def epoch(day):
    return int(datetime.strptime(day, '%Y-%m-%d').replace(tzinfo=timezone.utc).timestamp())
def read_history(path):
    with open(path) as f: rows = json.load(f)
    if not rows: raise ValueError('empty history')
    prev = -1
    for r in rows:
        if len(r) < 3 or not all(math.isfinite(float(x)) for x in r): raise ValueError('nonfinite/malformed bar')
        if r[0] <= prev or r[1] <= 0 or r[2] <= 0: raise ValueError('unsorted/duplicate/nonpositive bar')
        prev = r[0]
    return rows

def import_csv(path, out_dir, write=False, rights=False):
    if write and not rights: raise ValueError('write needs explicit data-rights confirmation')
    out = Path(out_dir).resolve(); repo = Path(__file__).resolve().parent
    if out == repo or repo in out.parents: raise ValueError('use a private directory outside the public repository')
    panels = {}
    with open(path, newline='') as f:
        for r in csv.DictReader(f):
            s = r['symbol'].strip()
            if not SYMBOL.fullmatch(s): raise ValueError('invalid symbol')
            v = [epoch(r['date']), float(r['open']), float(r['close']), float(r['volume'])]
            if not all(math.isfinite(x) for x in v) or min(v[1:3]) <= 0 or v[3] < 0: raise ValueError('invalid price/volume')
            panels.setdefault(s, []).append(v)
    if not panels: raise ValueError('empty CSV')
    # Validate every series before writing any file.
    for rows in panels.values():
        rows.sort(key=lambda x: x[0])
        if any(a[0] == b[0] for a,b in zip(rows, rows[1:])): raise ValueError('duplicate symbol/date')
    if write:
        out.mkdir(parents=True, exist_ok=True)
        for s,rows in panels.items():
            p=out/f'bars_{s}_1y.json'
            if p.exists(): raise ValueError('refuse overwrite; choose a new staging directory')
        for s,rows in panels.items():
            p=out/f'bars_{s}_1y.json'; tmp=p.with_suffix('.tmp')
            tmp.write_text(json.dumps(rows)); os.replace(tmp,p)
    return {'symbols':len(panels),'rows':sum(map(len,panels.values())), 'written':write,
            'source_rights_verified':False,'prices_adjusted_verified':False,'research_only':True}

def shadow(signals, history, initial=100000., fee=25., slippage_bps=10.):
    if initial <= 0 or fee < 0 or slippage_bps < 0 or slippage_bps >= 10000: raise ValueError('invalid capital/cost')
    if not signals: raise ValueError('no frozen signals')
    symbols={s for sig in signals for s in sig['weights']}
    if any(not SYMBOL.fullmatch(s) for s in symbols): raise ValueError('invalid symbol')
    if not symbols: raise ValueError('no symbols')
    for s in symbols:
        rows=history[s]
        if not rows or any(len(r)<3 or not all(math.isfinite(float(x)) for x in r) or min(r[1:3])<=0 for r in rows): raise ValueError('invalid history')
        if any(a[0]>=b[0] or int(a[0]//86400)==int(b[0]//86400) for a,b in zip(rows,rows[1:])): raise ValueError('duplicate/unsorted dates')
    bars={s:{int(r[0]//86400):r for r in history[s]} for s in symbols}
    # Require shared dates, not asynchronous cross-market marks.
    dates=sorted(set.intersection(*(set(x) for x in bars.values())))
    if len(dates) < 2: raise ValueError('insufficient aligned history')
    orders={}; prev=-1
    for sig in signals:
        d=epoch(sig['as_of'])//86400; weights=sig['weights']
        if d <= prev or d not in dates: raise ValueError('signals must be unique ordered observed dates')
        prev=d
        if any(not math.isfinite(w) or w < 0 for w in weights.values()) or sum(weights.values()) > 1+1e-10: raise ValueError('invalid long-only weights')
        future=[x for x in dates if x>d]
        if not future: raise ValueError('signal has no next open')
        orders[future[0]]=weights
    dates=[d for d in dates if d>=min(orders)]
    cash=initial; shares={s:0. for s in symbols}; curve=[]; trades=[]; peak=initial; drawdown=0.; costs=0.
    slip=slippage_bps/10000
    for d in dates:
        if d in orders:
            nav=cash+sum(shares[s]*bars[s][d][1] for s in symbols)
            target={s:nav*orders[d].get(s,0)/bars[s][d][1] for s in symbols}
            # Sell first, then fund buys from remaining cash including costs.
            for s in sorted(symbols):
                qty=max(0., shares[s]-target[s])
                if qty>1e-9:
                    gross=qty*bars[s][d][1]; charge=fee+gross*slip
                    if charge>cash+gross: raise ValueError('cost exceeds available capital')
                    cash+=gross-charge; shares[s]-=qty; costs+=charge
                    trades.append({'day':d,'symbol':s,'side':'sell','shares':qty,'cost':charge})
            for s in sorted(symbols):
                qty=max(0.,target[s]-shares[s]); price=bars[s][d][1]
                qty=min(qty,max(0.,(cash-fee)/(price*(1+slip))))
                if qty>1e-9:
                    gross=qty*price; charge=fee+gross*slip
                    cash-=gross+charge; shares[s]+=qty; costs+=charge
                    trades.append({'day':d,'symbol':s,'side':'buy','shares':qty,'cost':charge})
        value=cash+sum(shares[s]*bars[s][d][2] for s in symbols)
        peak=max(peak,value);drawdown=min(drawdown,value/peak-1)
        curve.append({'day':d,'equity':round(value,6),'cash':round(cash,6)})
    return {'status':'MECHANICAL_SHADOW_ONLY','validated_for_trading':False,'initial':initial,
            'final':curve[-1]['equity'],'net_return':curve[-1]['equity']/initial-1,
            'max_drawdown':drawdown,'costs':costs,'trades':trades,'curve':curve,
            'cash_baseline_return':0.,'notes':'No interest/dividends/impact; no independent holdout claim. Sequential buys can underfill targets when cash is limited.'}

class RegressionTests(unittest.TestCase):
    def histories(self): return {'SPY':[[epoch('2026-09-28'),100,100,1],[epoch('2026-09-29'),110,120,1],[epoch('2026-09-30'),120,90,1]]}
    def signals(self): return [{'as_of':'2026-09-28','weights':{'SPY':1.}}]
    def test_next_open(self):
        r=shadow(self.signals(),self.histories(),1000,0,0)
        self.assertAlmostEqual(r['final'],1000/110*90,5)
    def test_fee_reduces_value(self): self.assertLess(shadow(self.signals(),self.histories(),1000,10,0)['final'],shadow(self.signals(),self.histories(),1000,0,0)['final'])
    def test_slippage_reduces_value(self): self.assertLess(shadow(self.signals(),self.histories(),1000,0,10)['final'],shadow(self.signals(),self.histories(),1000,0,0)['final'])
    def test_no_margin(self): self.assertGreaterEqual(min(x['cash'] for x in shadow(self.signals(),self.histories(),1000,25,10)['curve']),-1e-6)
    def test_future_signal(self):
        with self.assertRaises(ValueError): shadow([{'as_of':'2026-09-30','weights':{'SPY':1}}],self.histories())
    def test_leverage(self):
        with self.assertRaises(ValueError): shadow([{'as_of':'2026-09-28','weights':{'SPY':1.1}}],self.histories())
    def test_duplicate_signals(self):
        with self.assertRaises(ValueError): shadow(self.signals()*2,self.histories())
    def test_calendar(self):
        from nightly_ml import latest_completed_session
        self.assertEqual(str(latest_completed_session(datetime(2026,10,6,20,31,tzinfo=timezone.utc))),'2026-10-06')
    def test_preclose(self):
        from nightly_ml import latest_completed_session
        self.assertEqual(str(latest_completed_session(datetime(2026,10,6,19,0,tzinfo=timezone.utc))),'2026-10-05')
    def test_stale_gate(self):
        from nightly_ml import audit
        with tempfile.TemporaryDirectory() as p:
            Path(p,'bars_SPY_1y.json').write_text(json.dumps(self.histories()['SPY']))
            self.assertFalse(audit(p,datetime(2026,10,6,21,tzinfo=timezone.utc))['refit_allowed'])
    def test_model_factor_causality(self):
        import numpy as np
        from ml_rank import factor_panel
        a=np.array([[i*86400,100+i*.1,100+i*.2,10] for i in range(200)])
        b=a.copy();b[180:,2]*=2
        self.assertTrue(np.allclose(factor_panel(a)[1][:40],factor_panel(b)[1][:40]))
    def test_import_validation(self):
        with tempfile.TemporaryDirectory() as p:
            src=Path(p,'in.csv');src.write_text('symbol,date,open,close,volume\nSPY,2026-09-28,100,101,1\n')
            self.assertFalse(import_csv(src,Path(p,'out'))['written'])
            with self.assertRaises(ValueError): import_csv(src,Path(p,'out'),True,False)
    def test_negative_weight(self):
        with self.assertRaises(ValueError): shadow([{'as_of':'2026-09-28','weights':{'SPY':-.1}}],self.histories())
    def test_duplicate_bar(self):
        h=self.histories();h['SPY'].append(h['SPY'][-1])
        with self.assertRaises(ValueError): shadow(self.signals(),h)
    def test_cash_only(self):
        r=shadow([{'as_of':'2026-09-28','weights':{'SPY':0}}],self.histories(),1000,25,10)
        self.assertEqual(r['final'],1000)
    def test_bad_bar(self):
        with tempfile.TemporaryDirectory() as p:
            f=Path(p,'bad.json');f.write_text('[[1,0,2]]')
            with self.assertRaises(ValueError): read_history(f)

def main():
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='command',required=True)
    sub.add_parser('self-test')
    q=sub.add_parser('import-csv');q.add_argument('csv');q.add_argument('--out-dir',required=True);q.add_argument('--write',action='store_true');q.add_argument('--rights-confirmed',action='store_true')
    q=sub.add_parser('shadow');q.add_argument('signals');q.add_argument('--data-dir',required=True);q.add_argument('--fee',type=float,required=True);q.add_argument('--slippage-bps',type=float,required=True);q.add_argument('--initial',type=float,default=100000);q.add_argument('--output',required=True)
    a=p.parse_args()
    if a.command=='self-test':
        r=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(RegressionTests));return 0 if r.wasSuccessful() else 1
    if a.command=='import-csv': print(json.dumps(import_csv(a.csv,a.out_dir,a.write,a.rights_confirmed),indent=2));return 0
    signals=json.loads(Path(a.signals).read_text());symbols={s for sig in signals for s in sig['weights']}
    if any(not SYMBOL.fullmatch(s) for s in symbols): raise ValueError('invalid symbol')
    hist={s:read_history(Path(a.data_dir)/f'bars_{s}_1y.json') for s in symbols}
    result=shadow(signals,hist,a.initial,a.fee,a.slippage_bps);Path(a.output).write_text(json.dumps(result,indent=2));print(result['status']);return 0
if __name__=='__main__': raise SystemExit(main())
