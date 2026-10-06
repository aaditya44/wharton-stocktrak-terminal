"""NYSE cash-session calendar for 2026-2028, verified against NYSE published calendar.
Fail closed outside supported years. All session arithmetic uses America/New_York.
"""
from datetime import datetime, date, time, timedelta, timezone
from zoneinfo import ZoneInfo
ET = ZoneInfo('America/New_York')
HOLIDAYS = {
2026: '01-01 01-19 02-16 04-03 05-25 06-19 07-03 09-07 11-26 12-25',
2027: '01-01 01-18 02-15 03-26 05-31 06-18 07-05 09-06 11-25 12-24',
2028: '01-17 02-21 04-14 05-29 06-19 07-04 09-04 11-23 12-25'}
EARLY = {2026: {'11-27','12-24'}, 2027: {'11-26'}, 2028: {'07-03','11-24'}}
def is_session(d):
    if d.year not in HOLIDAYS: raise ValueError('calendar unsupported year')
    return d.weekday() < 5 and d.strftime('%m-%d') not in HOLIDAYS[d.year].split()
def close_time(d):
    if not is_session(d): return None
    return datetime.combine(d,time(13 if d.strftime('%m-%d') in EARLY[d.year] else 16),ET)
def latest_completed_session(now=None, delay_minutes=30):
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None: raise ValueError('timezone required')
    local=now.astimezone(ET); d=local.date()
    for _ in range(10):
        close=close_time(d)
        if close and now >= close+timedelta(minutes=delay_minutes): return d
        d-=timedelta(days=1)
    raise ValueError('no completed session')

"""Observable daily-history status, independent of model fit/build timestamp."""
import json, os, glob
from datetime import datetime, timezone
from collections import Counter

HERE=os.path.dirname(os.path.abspath(__file__))
def audit(data_dir=None, now=None):
    now=now or datetime.now(timezone.utc); data_dir=data_dir or os.path.join(HERE,'data')
    expected=latest_completed_session(now).isoformat(); dates={}; invalid=[]
    for path in glob.glob(os.path.join(data_dir,'bars_*_1y.json')):
        sym=os.path.basename(path)[5:-8]
        try:
            rows=json.load(open(path))
            if not rows: raise ValueError('empty')
            ts=[float(r[0]) for r in rows]
            if any(b<=a for a,b in zip(ts,ts[1:])): raise ValueError('nonmonotonic')
            if any(len(r)<3 or min(float(r[1]),float(r[2]))<=0 for r in rows): raise ValueError('invalid price')
            dates[sym]=datetime.fromtimestamp(ts[-1],timezone.utc).strftime('%Y-%m-%d')
        except (ValueError,TypeError,KeyError,IndexError,json.JSONDecodeError): invalid.append(sym)
    us={s:d for s,d in dates.items() if '.' not in s}; fresh=[s for s,d in us.items() if d==expected]
    ratio=len(fresh)/len(us) if us else 0
    ready=ratio>=0.95 and dates.get('SPY')==expected
    return {'checked_at':now.isoformat(),'expected_session':expected,'history_latest_date':max(dates.values(),default=None),
        'daily_date_counts':dict(Counter(dates.values())), 'us_symbols':len(us),'fresh_us_symbols':len(fresh),
        'fresh_us_fraction':round(ratio,4),'spy_data_date':dates.get('SPY'),'invalid_symbols':invalid,'invalid_symbols_excluded':True,
        'status':'FRESH_RESEARCH_ONLY' if ready else 'STALE_HISTORY_BLOCKED',
        'refit_allowed':ready,'research_only':True,'validated_for_trading':False,
        'message':'Freshness is necessary, not proof of investment performance. No automated orders.' if ready else
          'Daily history is behind the completed session. Old ranks are not new recommendations. No refit or automated orders.',
        'symbol_dates':dates}

#!/usr/bin/env python3
"""Post-close research pipeline. Known-blocked Yahoo download is disabled.
Audit committed/imported daily history first. Stale inputs publish an explicit
blocked status and preserve prior fit and ranks; never stamp them fresh.
No portfolio mutation or trade integration exists here.
"""
import json,os,subprocess,sys

HERE=os.path.dirname(os.path.abspath(__file__)); DATA=os.path.join(HERE,'data')
def main():
    global prior_snapshot
    prior_snapshot=json.load(open(os.path.join(DATA,"ml_snapshot.json")))
    status=audit(); json.dump(status,open(os.path.join(DATA,'freshness.json'),'w'),indent=2)
    if not status['refit_allowed']:
        print('STALE_HISTORY_BLOCKED: no download retry, no refit; preserving last fit/ranks',flush=True)
        subprocess.run([sys.executable,os.path.join(HERE,'make_ml_snapshot.py')],check=True)
        mark_snapshot(status)
        subprocess.run([sys.executable,os.path.join(HERE,'build_site.py')],check=True)
        return 2
    # Refitting alone is experimental. Promotion to trade recommendations is disabled.
    env=dict(os.environ,ML_EVAL_EXCLUDE_SUFFIX='.NS,.HK,.L,.TO,.DE,.PA,.MI,.MC,.AS,.BR')
    subprocess.run([sys.executable,os.path.join(HERE,'ml_rank.py')],env=env,check=True)
    # Both ranks are experimental; identical data/date gate, separate display.
    env["ML_RANK_INTL"]="1"
    subprocess.run([sys.executable,os.path.join(HERE,"ml_rank.py")],env=env,check=True)
    subprocess.run([sys.executable,os.path.join(HERE,'make_ml_snapshot.py')],check=True)
    mark_snapshot(status)
    subprocess.run([sys.executable,os.path.join(HERE,'build_site.py')],check=True)
    return 0


def mark_snapshot(status):
    p=os.path.join(DATA,'ml_snapshot.json'); snap=json.load(open(p)); rank=json.load(open(os.path.join(DATA,'ml_ranking.json')))
    snap['market_data_date']=datetime.fromtimestamp(rank['date']*86400,timezone.utc).strftime('%Y-%m-%d')
    snap['expected_session']=status['expected_session'];snap['data_status']=status['status']
    snap['freshness']={k:v for k,v in status.items() if k!='symbol_dates'}
    snap['research_only']=True;snap['validated_for_trading']=False
    snap['fit_at']=snap['date'] if status['refit_allowed'] else prior_snapshot.get('fit_at',prior_snapshot.get('date','unverified'))
    snap['date']=snap['fit_at'];snap['note']='Experimental 21-session ranking, not a timing or profit forecast. No automated orders.'
    json.dump(snap,open(p,'w'),indent=2)

if __name__=='__main__': sys.exit(main())
