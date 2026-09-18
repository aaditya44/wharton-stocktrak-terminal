#!/usr/bin/env python3
"""build_site.py - generate the StockTrak Research Terminal (single self-contained index.html).

Reads cached price bars from data/, computes the research analytics
(overnight/intraday decomposition, day-of-week breakdown, equity curves),
and emits one portable HTML file with client-side filtering. No external assets.
"""
import base64, csv, datetime as dt, io, json, math, os, statistics

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
NOW = dt.datetime.now(dt.timezone(dt.timedelta(hours=5, minutes=30)))  # IST

# ---------- analytics ----------
def load_bars(symbol, rng="1y"):
    p = os.path.join(DATA, f"bars_{symbol.replace('^','I_').replace('=','_')}_{rng}.json")
    return json.load(open(p)) if os.path.exists(p) else None

def decompose(rows):
    out = []
    for i in range(1, len(rows)):
        t, o, c = rows[i][0], rows[i][1], rows[i][2]
        pc = rows[i-1][2]
        out.append((dt.datetime.fromtimestamp(t, dt.timezone.utc), math.log(o/pc), math.log(c/o)))
    return out

def st(xs):
    if len(xs) < 30: return None
    m = statistics.mean(xs)*252*100
    v = statistics.pstdev(xs)*math.sqrt(252)*100
    return dict(n=len(xs), mean=round(m,1), vol=round(v,1),
                sharpe=round(m/v,2) if v else None,
                hit=round(sum(1 for x in xs if x>0)/len(xs)*100))

def cum_curve(pairs, idx):
    curve, acc = [], 0.0
    for p in pairs:
        acc += p[idx]
        curve.append((p[0], math.exp(acc)-1))
    return curve

def fig_b64(series, title, labels):
    plt.style.use("dark_background")
    fig, ax = plt.subplots(figsize=(7.2, 3.2), dpi=110)
    for s, lab in zip(series, labels):
        ax.plot([p[0] for p in s], [p[1]*100 for p in s], label=lab, linewidth=1.4)
    ax.set_title(title, fontsize=10); ax.set_ylabel("cumulative %")
    ax.legend(fontsize=8); ax.grid(alpha=.25)
    fig.autofmt_xdate(); fig.tight_layout()
    buf = io.BytesIO(); fig.savefig(buf, format="png"); plt.close(fig)
    return base64.b64encode(buf.getvalue()).decode()

DOW = ["Mon","Tue","Wed","Thu","Fri"]
def dow_stats(pairs, idx):
    by = {d: [] for d in range(5)}
    for p in pairs:
        if p[0].weekday() < 5: by[p[0].weekday()].append(p[idx])
    out = []
    for d in range(5):
        xs = by[d]
        if xs:
            out.append((DOW[d], len(xs), round(statistics.mean(xs)*100, 3),
                        round(sum(1 for x in xs if x > 0)/len(xs)*100)))
    return out

analytics = {}   # symbol -> dict
for sym in ["AAPL", "^GSPC"]:
    rows = load_bars(sym)
    if not rows: continue
    pairs = decompose(rows)
    on = [p[1] for p in pairs]; intra = [p[2] for p in pairs]
    analytics[sym] = dict(
        n=len(rows), on=st(on), intra=st(intra),
        on_curve=cum_curve(pairs, 1), in_curve=cum_curve(pairs, 2),
        dow_on=dow_stats(pairs, 1), dow_in=dow_stats(pairs, 2))

import engine
RANKING = engine.compute()

import client
CLIENT = client.compute()

charts = {}
for sym, a in analytics.items():
    name = "S&P 500 index" if sym == "^GSPC" else sym
    charts[sym] = fig_b64([a["on_curve"], a["in_curve"]],
                          f"{name}: 1y cumulative return - overnight vs intraday",
                          ["overnight (close to open)", "intraday (open to close)"])

# ---------- content ----------
PORTFOLIO = [
    ("NVDA (205 sh)", "Mega-cap tech", "Core leader", "Averaged up 65 sh @ $218.12 on 09-17 (Exp 7); +2.5% same session"),
    ("SOXL (139 sh)", "Semis 3x leverage", "Momentum experiment", "130 sh @ $113.66 (Exp 6, half-sized on +9% gap) + 9 of 125 partial @ $115.07; 116-sh completion pending"),
    ("HCWC (4,000 sh)", "Merger arb", "Event experiment", "User trade @ ~$13.77 ($55,080); -19.3% (-$10,640) day one; user instructed HOLD for merger outcome unless thesis breaks"),
    ("TQQQ", "Nasdaq 3x leverage", "Beta sleeve", "-2.2% in the 09-17 hawkish-Fed selloff; high gap risk"),
    ("XLE", "Energy", "Geopolitics hedge", "XOM leg SOLD 09-17 (59 sh ~$163.32): thesis broke after crude's third down day + Saudi rerouting; correct cut"),
    ("UUP", "US dollar", "Working hedge", "Gained during the 09-17 selloff; dampens equity beta"),
    ("GLD", "Gold", "Defensive ballast", "Low correlation sleeve"),
    ("ITA / LMT", "Defense", "Thematic", "Geopolitical escalation upside"),
    ("2.75% Feb-28 Treasury", "Rates", "User's own buy", "50 units (~$49k, ~16%) bought by Aaditya 09-16; rated 6/10 fit for an aggressive target"),
    ("AAPL", "Mega-cap tech", "Core quality", "Stayed green through the 09-17 selloff"),
]

IDEAS = [
    dict(t="HCWC", theme="Event", thesis="HOST acquisition spread: price should converge toward deal terms as closing approaches",
         catalyst="Merger milestones, filings, closing date", entry="Near close, sized small", exit="Deal close, or immediately on delay/cancel news",
         conf="Medium", downside="Deal break gaps the spread wide open overnight; position already -19.3% day one and held by user instruction"),
    dict(t="SOXL", theme="Momentum", thesis="Semis relative strength; complete the 116-share tranche only while momentum holds",
         catalyst="Semis news, NVDA earnings halo, SOX index trend", entry="Pre-close window 30-15 min before 4pm ET",
         exit="20-40% spike rule, or pre-open exit if overnight news breaks the thesis", conf="Medium",
         downside="3x daily reset: a -10% overnight gap in semis is -30% here"),
    dict(t="Overnight-gap basket", theme="Overnight", thesis="Research hypothesis H1: overnight returns dominate intraday for index-level exposure (JFE 2019 evidence)",
         catalyst="Between-session news cycle", entry="Last 15-30 min of session", exit="First minutes after next open, never same-day (rules)",
         conf="Research", downside="Weekend gaps compound ~3 days of news; keep experiment capped"),
    dict(t="NVDA", theme="Quality", thesis="Mega-cap quality that stayed green in the Fed selloff; core holding",
         catalyst="AI/datacenter news flow", entry="Hold / add on weakness", exit="Thesis review weekly, not on noise",
         conf="High", downside="Crowded positioning; sharp but recoverable drawdowns"),
    dict(t="UUP", theme="Hedge", thesis="Dollar strength persisted through the selloff; offsets equity beta",
         catalyst="Fed path, rate differentials", entry="Hold", exit="When Fed turns dovish or equities stabilize",
         conf="Medium", downside="Slow bleed if risk-on returns"),
    dict(t="XLE", theme="Energy", thesis="Middle East escalation premium in crude",
         catalyst="Geopolitics, OPEC", entry="Hold small", exit="De-escalation headlines",
         conf="Low", downside="Gap down on any ceasefire headline"),
]

EXPERIMENTS = [
    ("2026-09-16", "Mandate set", "High risk tolerance, heavy diversification, 30% ROI target pushed back as unrealistic for 9 days; risk-adjusted focus adopted", "Operating mandate"),
    ("2026-09-17", "Fed stress test", "Hawkish presser drove slow selloff: TQQQ -2.2%, XLE -2.33%; UUP hedge and mega-cap quality worked", "Hedge validated"),
    ("2026-09-17", "Exp 6: semis momentum", "BUY 130 SOXL, half-sized because of a +9% gap", "+1.0% by 14:41; open"),
    ("2026-09-17", "Exp 7: average up into leader", "BUY 65 NVDA @ $218.12 into strength", "+2.5% by 14:32; open, 205 sh total"),
    ("2026-09-17", "HCWC merger event", "User bought 4,000 sh; same-day -19.3%", "HOLD per user instruction unless thesis-breaking news"),
    ("2026-09-17", "Partial-fill lesson", "SOXL order filled 9 of 125 shares; standing rule: verify actual filled quantity on every order", "Process fix adopted"),
    ("2026-09-17", "Exp 8: third-party signal labels", "Do published strong-buy/sell labels predict? INDP Signal #1 test", "+18.2% at 1 day; multi-day checkpoint pending"),
    ("2026-09-17", "Exp 9: mean reversion", "Fallen spike names, 1-3% sizing, max 2-3 names", "Registered"),
    ("2026-09-18", "Exp 10: composite forward test", "Pre-registered 2026-09-18 01:40 IST, before entry: buy the model's #1 full-universe composite (MSFT, score +0.596) ~10:00 AM ET, ~15-20 sh within cash limits. Fixed weights 0.30 3m mom / 0.15 1m mom / 0.15 overnight Sharpe / 0.15 low-vol / 0.15 trend / 0.10 52w-high. Entry factor snapshot: 3m +31.5%, vol 21.4% (inside 40% band), overnight Sharpe -0.15 (disclosed weak factor)", "ENTERED 2026-09-18 9:55am ET: 10 sh @ $494.09, conf A50BD22B, full fill verified. No gap distortion (opened -0.88%). Weekend-locked. Marks pending: close / +1d / +2d"),
    ("2026-09-18", "Overnight experiment", "Buy near close, monitor between sessions, reassess pre-open, exit after open (no-day-trading compliant)", "Approved; sizing autonomous"),
    ("2026-09-18", "Standing autonomy", "User granted trade autonomy; daily rhythm: pre-open brief 6:30pm IST, pre-close trades 1:00am IST, hourly in-market checks", "Mandate updated"),
    ("2026-09-18", "Algorithm rotation mandate", "User confirmed autonomous algorithm-driven buys/sells without per-trade approval, subject to live verification and constraints. AAPL protected core; HOST under separate conditional exit (platform has not processed the HCWC->HOST ticker change - exit armed, symbol not yet tradeable)", "Mandate updated; every fill logged for evaluation"),
]

TRADES = [
    ("2026-09-16", "2.75% UST Feb-2028", "BUY", "50 units (~$49k)", "Executed by Aaditya himself at the open; reviewed 6/10 for an aggressive target"),
    ("2026-09-17 09:44 ET", "XOM", "SELL", "59 sh ~$163.32", "Conf 6EF52922. Energy thesis broke (crude third down day, Saudi rerouting); avoided further decline - correct cut"),
    ("2026-09-17 09:46 ET", "SOXL", "BUY", "130 sh ~$113.66 ($14,774.80)", "Conf 92E51EB6. Exp 6 semis momentum, half-sized on +9% gap; +1.0% by 14:41"),
    ("2026-09-17 09:46 ET", "NVDA", "BUY", "65 sh @ $218.12 ($14,177.80)", "Conf E741EA02. Exp 7 average up into strongest leader; +2.5% by 14:32; position now 205 sh"),
    ("2026-09-17 10:46 ET", "HCWC", "BUY (user)", "4,000 sh ~$13.77 ($55,080)", "Host Digital AI merger thesis; -19.3% (-$10,640) same day; user instructed HOLD for merger outcome unless thesis-breaking news"),
    ("2026-09-17 14:35 ET", "SOXL", "BUY", "9 of 125 filled ~$115.07 ($1,035.63)", "Conf 26365B54. Partial fill - exposed the verification gap now in the standing rules; 116-sh completion planned pre-close"),
    ("2026-09-18 AM ET", "INDP", "SELL (user)", "500 of 1,000 sh @ $3.80 ($1,875 net)", "Conf 40A41699. User instructed the trim; de-risks the micro-cap sleeve, 500 sh remain"),
    ("2026-09-18 pre-close ET", "SOXL", "BUY", "8 sh ~$115.25 (~$922); 147 sh total, blended $114.04", "Platform qty-reduced from 116 near the close (known quirk - size earlier in session); position now ~147 sh"),
    ("2026-09-18 pre-close ET", "INTC", "BUY", "50 sh @ $109.50 ($5,475)", "Conf 520FCC3F. Exp 9 semis/foundry momentum entry"),
    ("2026-09-18 09:55 ET", "MSFT", "BUY", "10 sh @ $494.09 ($4,940.90)", "Conf A50BD22B. Exp 10 composite forward test, rank #1/64 +0.596, vol 21.4% in-band; full fill, no reduction; weekend-locked"),    ("2026-09-18 10:00 ET", "SOXL", "SELL", "147 sh @ $118.05 ($17,328.36 net)", "Order 38B31FA0. Model's #68 AVOID exited into semis strength; +$559 (+3.3%) round trip; validates H2's exit-into-strength execution. Cash $22,685.90, 30/200 trades"),
]

METHODOLOGY = [
    ("Data sources (verified 2026-09-18)", "Yahoo Finance chart API via the agent fetch path for daily/intraday bars (per-symbol availability is inconsistent - ETFs often blocked; every successful pull is cached so history is never re-fetched). StockTrak account snapshots at scheduled checkpoints only - no aggressive scraping. SEC filings and news via web fetch/search at event time."),
    ("Competition rules encoded", "$25 commission per trade, no short selling, no margin, no same-day exits (a position bought today cannot be sold today). Practice period resets 2026-09-25 16:00 ET; real competition starts 2026-09-28 09:30 ET; ~$300k starting value."),
    ("Anti-overfitting", "Hypotheses pre-registered with an economic rationale before testing. Train/validation split plus walk-forward. Multiple-testing control across bucket grids. Minimum n=30 per cell or the cell is labeled anecdote. Max 2-3 parameters per rule. Every backtest carries $25/trade commission plus a slippage haircut. Effects must survive a half-sample split."),
    ("Known limitations", "Only 2 symbols ingested so far (252 daily bars each); ETF fetch path is unreliable and being worked around. Five practice days left cannot produce statistical significance - live trading data validates, historical data discovers. Half of all backtest findings should be assumed to fail live."),
]

CASE_STUDY = [
    "CLIENT (from the official case study PDF, 2026-09-18): Laura Gao - bestselling author, illustrator, entrepreneur, educator (born Wuhan, raised Texas; Wharton Statistics 2018; ex-tech PM; The Wuhan I Know 2020; Messy Roots). Living expenses covered outside the portfolio.",
    "CASH FLOWS: $300,000 invested at the start of 2027; +$150,000 at the start of 2028; no other additions or withdrawals before 2033.",
    "PRIMARY LIABILITY: ten annual $50,000 operating payments for a Taiwan creative residency, 2033-2042, fixed (not inflation-adjusted), funded by the portfolio with a HIGH DEGREE OF CERTAINTY - no reliance on co-sponsors for this. At the start of 2033 an operating reserve is set aside; we must recommend its size, composition, and glide path, and define what 'high certainty' means with assumptions.",
    "SECONDARY GOAL: a responsible 2033 facility contribution from the remaining portfolio - no predetermined size; preserve financial flexibility; explain favorable/unfavorable market outcomes.",
    "2031 CO-SPONSOR COMMUNICATION: recommend a credible dollar range for the 2033 contribution with a stated confidence level, plus draft fundraising language. The range must not impair the operating commitment.",
    "RISK POSTURE (verbatim case): she took 'thoughtful risks' as an entrepreneur but wants a recommended balance between pursuing growth and protecting the capital required for her goals. Mapping this to a vol band is OUR assumption, flagged in Client mode - not a case fact.",
    "EVALUATION (from the guide): NOT judged on returns, ranking, trade count, or beating other teams. Judged on one cohesive strategy connecting client goals -> research -> portfolio decisions -> recommendations. WInS P&L is demonstration evidence only; projections start from the case cash flows, not from WInS gains.",
    "DELIVERABLES (official schedule, all 5:00 PM ET): Trading Notes Analysis - 3 notes showing decisions that supported/tested/refined strategy - due Fri Oct 23, submissions open Mon Oct 12. Investment Policy Statement due Fri Nov 6, submissions open Mon Oct 26; trading ends and the portfolio freezes Nov 6, strategy may not be revised after. Final Report due Fri Dec 4, submissions open Nov 9. School Documentation also due Fri Dec 4, submissions open Nov 9.",
    "UNKNOWN PRESERVED: the approved WInS securities universe and detailed deliverable requirements live on SurveyMonkey Apply (Pages tab) - not in the supplied PDFs. Confirm before assuming every screened symbol is WInS-eligible.",
    "HOW THIS TERMINAL MAPS: Screener = investable-universe evidence; Client mode = Laura's mandate and constraints applied to rankings; Experiment/Trade logs = Trading Notes raw material (each fill has a dated rationale); Backtests + Methodology = IPS evidence base.",
]

HYPOTHESES = [
    ("H1", "Overnight returns dominate intraday at index level (Lou/Polk/Skouras, JFE 2019)", "TESTING - early data supportive for ^GSPC, not AAPL"),
    ("H2", "3x leveraged ETFs (SOXL/TQQQ) bleed via daily-reset decay in sideways volatility", "REGISTERED"),
    ("H3", "Day-of-week effects in our universe", "EXPECTED NULL - demonstrates discipline either way"),
    ("H4", "Fed-day and event windows carry outsized overnight moves", "REGISTERED"),
    ("H5", "Pre-close semis momentum continues into next open", "REGISTERED"),
]

# ---------- html ----------
def esc(s): return s.replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")

def conf_badge(c):
    col = {"High":"#2da44e","Medium":"#bf8700","Low":"#cf222e","Research":"#8250df"}[c]
    return f'<span class="badge" style="background:{col}">{c}</span>'

def sig_badge(s):
    col = {"BUY":"#2da44e","WATCH":"#bf8700","AVOID":"#cf222e"}[s]
    return f'<span class="badge" style="background:{col}">{s}</span>'

screen_rows = ""
for r in RANKING:
    tip = "score parts: " + ", ".join(f"{k} {v:+.3f}" for k, v in r["contrib"].items())
    screen_rows += (f'<tr data-sector="{r["sector"]}" data-signal="{r["signal"]}" title="{tip}">'
        f'<td>{r["rank"]}</td><td><b>{r["symbol"]}</b></td><td>{r["sector"]}</td>'
        f'<td><b>{r["score"]:+.3f}</b></td><td>{r["ret_1m"]:+.1f}%</td><td>{r["ret_3m"]:+.1f}%</td>'
        f'<td>{r["vol20"]}%</td><td>{r["on_sharpe"]:+.2f}</td><td>{r["trend"]}%</td><td>{r["hi52"]}%</td>'
        f'<td>{sig_badge(r["signal"])}</td><td>{r["confidence"]}</td></tr>')
sectors = sorted({r["sector"] for r in RANKING})
sector_opts = "".join(f'<option value="{s}">{s}</option>' for s in sectors)
n_cached = len(RANKING)
n_total = sum(1 for l in open(os.path.join(HERE, "universe.txt")) if l.strip())

cpos_rows = "".join(
    f'<tr data-sym="{p["symbol"]}" data-px="{p["price"]}"><td><b>{p["symbol"]}</b></td>'
    f'<td><input class="c-sh" type="number" value="{p["shares"]}" style="width:80px" onchange="crecompute()"></td>'
    f'<td>${p["price"]:,.2f}</td><td class="c-val">${p["value"]:,.0f}</td><td class="c-w">{p["weight"]}%</td><td>{p.get("note","")}</td></tr>'
    for p in CLIENT["positions"])
cflag_items = "".join('<p class="flag">- ' + f + '</p>' for f in CLIENT["flags"])
crank_rows = ""
for r in CLIENT["client_ranking"]:
    crank_rows += ('<tr data-vol="' + str(r["vol20"]) + '" data-sector="' + r["sector"] + '" data-score="' + str(r["score"]) + '">'
        '<td class="cr">' + str(r["client_rank"]) + '</td><td><b>' + r["symbol"] + '</b></td><td>' + r["sector"] + '</td>'
        '<td>' + format(r["score"], "+.3f") + '</td><td class="cm">x' + str(r["suit_mult"]) + '</td>'
        '<td class="cs"><b>' + format(r["client_score"], "+.3f") + '</b></td>'
        '<td>' + sig_badge(r["signal"]) + '</td><td class="cn">' + r["suit_note"] + '</td></tr>')
_client_tpl = open(os.path.join(HERE, "client_section.html")).read()
_client_html = (_client_tpl.replace("{{CLIENT_NAME}}", CLIENT["profile"].get("client_name","Client")).replace("{{LIFE_STAGE}}", CLIENT["profile"]["life_stage"])
    .replace("{{GOAL}}", CLIENT["profile"]["goal"]).replace("{{HORIZON}}", str(CLIENT["profile"]["horizon_months"]))
    .replace("{{BOOK}}", format(CLIENT["book"], ",.0f")).replace("{{CPOS_ROWS}}", cpos_rows)
    .replace("{{CFLAG_ITEMS}}", cflag_items).replace("{{CRANK_ROWS}}", crank_rows))
_client_js = open(os.path.join(HERE, "client_js.js")).read().replace("{{BOOK}}", repr(CLIENT["book"]))

ideas_rows = "".join(
    f'<tr data-theme="{i["theme"]}" data-conf="{i["conf"]}">'
    f'<td><b>{esc(i["t"])}</b></td><td>{i["theme"]}</td><td>{esc(i["thesis"])}</td>'
    f'<td>{esc(i["catalyst"])}</td><td>{esc(i["entry"])}</td><td>{esc(i["exit"])}</td>'
    f'<td>{conf_badge(i["conf"])}</td><td>{esc(i["downside"])}</td></tr>' for i in IDEAS)

backtest_blocks = ""
for sym, a in analytics.items():
    name = "S&P 500 (^GSPC)" if sym == "^GSPC" else sym
    dow_rows = "".join(
        f"<tr><td>{d}</td><td>{n}</td><td>{m:+.3f}%</td><td>{h}%</td></tr>"
        for d, n, m, h in a["dow_on"])
    backtest_blocks += f"""
    <div class="card"><h3>{name} - 1 year, {a['n']} daily bars</h3>
    <table><tr><th>Component</th><th>n</th><th>Ann. mean</th><th>Ann. vol</th><th>Sharpe</th><th>Hit rate</th></tr>
    <tr><td>Overnight (close&rarr;open)</td><td>{a['on']['n']}</td><td>{a['on']['mean']:+.1f}%</td><td>{a['on']['vol']}%</td><td>{a['on']['sharpe']:+.2f}</td><td>{a['on']['hit']}%</td></tr>
    <tr><td>Intraday (open&rarr;close)</td><td>{a['intra']['n']}</td><td>{a['intra']['mean']:+.1f}%</td><td>{a['intra']['vol']}%</td><td>{a['intra']['sharpe']:+.2f}</td><td>{a['intra']['hit']}%</td></tr></table>
    <img class="chart" src="data:image/png;base64,{charts[sym]}" alt="equity curves">
    <h4>Overnight mean return by weekday (H3, exploratory - not adjusted for multiple testing)</h4>
    <table><tr><th>Weekday</th><th>n</th><th>Mean overnight</th><th>Hit</th></tr>{dow_rows}</table>
    </div>"""

exp_rows = "".join(f"<tr><td>{d}</td><td><b>{esc(t)}</b></td><td>{esc(x)}</td><td>{esc(o)}</td></tr>" for d, t, x, o in EXPERIMENTS)
trade_rows = "".join(f"<tr><td>{d}</td><td>{esc(s)}</td><td>{esc(a)}</td><td>{esc(q)}</td><td>{esc(n)}</td></tr>" for d, s, a, q, n in TRADES)
port_rows = "".join(f"<tr><td><b>{esc(s)}</b></td><td>{esc(t)}</td><td>{esc(r)}</td><td>{esc(n)}</td></tr>" for s, t, r, n in PORTFOLIO)
meth_blocks = "".join(f'<div class="card"><h3>{esc(h)}</h3><p>{esc(b)}</p></div>' for h, b in METHODOLOGY)
hyp_rows = "".join(f"<tr><td>{h}</td><td>{esc(t)}</td><td>{esc(s)}</td></tr>" for h, t, s in HYPOTHESES)
case_items = "".join(f"<li>{esc(x)}</li>" for x in CASE_STUDY)
themes = sorted({i["theme"] for i in IDEAS})
theme_opts = "".join(f'<option value="{t}">{t}</option>' for t in themes)

CSS = """
body{background:#0d1117;color:#e6edf3;font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;margin:0}
header{padding:18px 26px;border-bottom:1px solid #30363d;display:flex;flex-wrap:wrap;gap:18px;align-items:baseline}
header h1{font-size:20px;margin:0} header .sub{color:#8b949e;font-size:13px}
nav{padding:0 26px;border-bottom:1px solid #30363d;display:flex;flex-wrap:wrap}
nav button{background:none;border:none;color:#8b949e;padding:12px 14px;font-size:14px;cursor:pointer;border-bottom:2px solid transparent}
nav button.active{color:#58a6ff;border-bottom-color:#58a6ff}
section{display:none;padding:20px 26px} section.active{display:block}
.card{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:16px 18px;margin-bottom:16px}
table{border-collapse:collapse;width:100%;font-size:13px}
th,td{border:1px solid #30363d;padding:6px 9px;text-align:left;vertical-align:top}
th{background:#21262d} .badge{color:#fff;border-radius:10px;padding:2px 8px;font-size:11px}
.chart{max-width:100%;border-radius:6px;margin:10px 0}
.filters{margin-bottom:12px;display:flex;gap:10px;flex-wrap:wrap}
.filters select,.filters input{background:#0d1117;color:#e6edf3;border:1px solid #30363d;border-radius:6px;padding:6px 9px;font-size:13px}
.warn{border-left:3px solid #bf8700;padding:8px 12px;background:#161b22;margin-bottom:16px;font-size:13px}
h2{margin:0 0 14px;font-size:17px} h3{font-size:14px;margin:0 0 10px} h4{font-size:13px;margin:14px 0 6px}
p{font-size:13px;line-height:1.55;margin:6px 0} ol{font-size:13px;line-height:1.7}
footer{padding:16px 26px;color:#8b949e;font-size:12px;border-top:1px solid #30363d}
"""

JS = """
function show(id){document.querySelectorAll('section').forEach(s=>s.classList.remove('active'));
document.querySelectorAll('nav button').forEach(b=>b.classList.remove('active'));
document.getElementById(id).classList.add('active');
document.querySelector('nav button[data-t="'+id+'"]').classList.add('active');}
function filt(){var th=document.getElementById('f-theme').value,cf=document.getElementById('f-conf').value,
q=document.getElementById('f-q').value.toLowerCase();
document.querySelectorAll('#ideas tbody tr').forEach(function(r){
var ok=(!th||r.dataset.theme===th)&&(!cf||r.dataset.conf===cf)&&(!q||r.textContent.toLowerCase().includes(q));
r.style.display=ok?'':'none';});}
window.addEventListener('DOMContentLoaded',function(){show('screener');});
{_client_js}
function filt2(){var se=document.getElementById('s-sector').value,si=document.getElementById('s-signal').value,
q=document.getElementById('s-q').value.toLowerCase();
document.querySelectorAll('#screen tbody tr').forEach(function(r){
var ok=(!se||r.dataset.sector===se)&&(!si||r.dataset.signal===si)&&(!q||r.textContent.toLowerCase().includes(q));
r.style.display=ok?'':'none';});}
"""

html = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>StockTrak Research Terminal v0.5</title><style>{CSS}</style></head><body>
<header><h1>StockTrak Research Terminal <span style="color:#58a6ff">v0.5</span></h1>
<span class="sub">Wharton competition practice account &middot; generated {NOW:%Y-%m-%d %H:%M} IST &middot; all statistics from cached daily bars, sources dated</span></header>
<nav>
<button data-t="screener" onclick="show('screener')">Screener</button>
<button data-t="client" onclick="show('client')">Client mode</button>
<button data-t="ideas" onclick="show('ideas')">Ranked ideas</button>
<button data-t="backtests" onclick="show('backtests')">Backtests</button>
<button data-t="risk" onclick="show('risk')">Portfolio risk</button>
<button data-t="experiments" onclick="show('experiments')">Experiment log</button>
<button data-t="trades" onclick="show('trades')">Trade log</button>
<button data-t="methodology" onclick="show('methodology')">Methodology</button>
<button data-t="casestudy" onclick="show('casestudy')">Case study</button>
</nav>

<section id="screener"><h2>Universe screener - explainable buy/sell ranking</h2>
<div class="warn">Cross-sectional ranking over the StockTrak-eligible universe ({n_cached} of {n_total} symbols ingested). Score = fixed a-priori weights: 30% 3-month momentum, 15% 1-month momentum, 15% overnight-return Sharpe, 15% low volatility, 15% trend quality, 10% 52w-high proximity. No fitted parameters: the weights are declared before testing, which is the first defense against overfitting. Hover a row to see each factor's contribution to its score. Top quartile = BUY candidates, bottom quartile = AVOID, rest WATCH. Research output, not auto-execution.</div>
<div class="filters">
<select id="s-sector" onchange="filt2()"><option value="">All sectors</option>{sector_opts}</select>
<select id="s-signal" onchange="filt2()"><option value="">All signals</option><option>BUY</option><option>WATCH</option><option>AVOID</option></select>
<input id="s-q" oninput="filt2()" placeholder="Search symbol..."></div>
<div class="card"><table id="screen"><thead><tr><th>#</th><th>Symbol</th><th>Sector</th><th>Score</th><th>1M</th><th>3M</th><th>Vol 20d</th><th>On Sharpe</th><th>Trend</th><th>52w hi</th><th>Signal</th><th>Data</th></tr></thead>
<tbody>{screen_rows}</tbody></table></div></section>

{_client_html}

<section id="ideas"><h2>Ranked idea shortlist</h2>
<div class="warn">Research shortlist, not auto-execution. Every idea needs a defensible thesis before a trade; the StockTrak notes field records it in natural language.</div>
<div class="filters" id="ideas-f">
<select id="f-theme" onchange="filt()"><option value="">All themes</option>{theme_opts}</select>
<select id="f-conf" onchange="filt()"><option value="">All confidence</option><option>High</option><option>Medium</option><option>Low</option><option>Research</option></select>
<input id="f-q" oninput="filt()" placeholder="Search thesis, catalyst, exit..."></div>
<table id="ideas"><thead><tr><th>Idea</th><th>Theme</th><th>Thesis</th><th>Catalyst</th><th>Entry</th><th>Exit rule</th><th>Confidence</th><th>Expected downside</th></tr></thead>
<tbody>{ideas_rows}</tbody></table></section>

<section id="backtests"><h2>Backtests: overnight vs intraday decomposition (H1)</h2>
<div class="warn">Historical discovery only: $25/trade commission and slippage apply to any traded version. Day-of-week rows are exploratory and unadjusted for multiple testing.</div>
{backtest_blocks}
<div class="card"><h3>Hypothesis register</h3>
<table><tr><th>ID</th><th>Hypothesis</th><th>Status</th></tr>{hyp_rows}</table></div></section>

<section id="risk"><h2>Portfolio risk snapshot (verified through the 2026-09-17 session)</h2>
<div class="warn">Positions verified through the 2026-09-17 session. Largest structural risks: HCWC event risk (~$44k after -19.3% on day one, user-mandated HOLD), overnight gaps in the 3x sleeves (SOXL 139 sh, TQQQ). Positions bought today cannot be sold today - gap risk is undiversifiable within a session.</div>
<div class="card"><table><tr><th>Sleeve</th><th>Theme</th><th>Role</th><th>Note</th></tr>{port_rows}</table></div></section>

<section id="experiments"><h2>Experiment log</h2>
<div class="card"><table><tr><th>Date</th><th>Experiment</th><th>What happened / design</th><th>Outcome / status</th></tr>{exp_rows}</table></div></section>

<section id="trades"><h2>Trade log (dated, auditable)</h2>
<div class="card"><table><tr><th>Date</th><th>Instrument</th><th>Side</th><th>Quantity</th><th>Note</th></tr>{trade_rows}</table></div></section>

<section id="methodology"><h2>Methodology</h2>{meth_blocks}</section>

<section id="casestudy"><h2>Client case - Laura Gao (Wharton 2026-2027)</h2>
<div class="card"><p>From the three official competition PDFs (case study, strategy roadmap, competition guide) supplied 2026-09-18. Competition documents override earlier generic assumptions.</p><ol>{case_items}</ol></div></section>

<footer>StockTrak Research Terminal v0.5 &middot; Python-generated, single-file, no external assets &middot; data: Yahoo Finance daily bars (cached 2026-09-18), StockTrak scheduled snapshots &middot; built for the Wharton competition practice period</footer>
<script>{JS}</script></body></html>"""

out = os.path.join(HERE, "index.html")
open(out, "w").write(html)
print("wrote", out, f"{len(html)/1024:.0f} KB")
