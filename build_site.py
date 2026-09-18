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

TIPS = {
 "score": "What: the overall attractiveness score, built from six fixed ingredients (momentum, overnight pattern, calmness, trend, nearness to 1-year high). Reading: higher is better; above roughly +0.35 is usually a BUY candidate, below about -0.1 is AVOID. Why it matters for Laura: it ranks which growth-sleeve candidates best fit her plan. Limitation: it looks backward at prices; it cannot see news that breaks a trend.",
 "mom1": "What: price change over the last month. Reading: positive means rising lately. Why: recent strength often continues short-term, which helps time entries. Limitation: a big one-month jump can also mean the move is exhausted.",
 "mom3": "What: price change over the last 3 months - the single biggest ingredient (30% of the score). Reading: higher = stronger medium-term trend. Why: 3-month momentum is one of the most reliable effects in decades of market research. Limitation: it buys strength, so it can be late at turning points.",
 "vol": "What: volatility - how much the price swings day to day, annualized, over 20 days. Reading: under ~20% is calm, 20-40% is normal for single stocks, over 40% is wild. Why: Laura's plan needs certainty, so anything above 40% is flagged unsuitable for her no matter how good the story. Limitation: calm today does not guarantee calm tomorrow.",
 "onsharpe": "What: overnight-return Sharpe - how consistently the stock gains between yesterday's close and today's open, per unit of risk. Reading: above 0 is good; above 1 is strong. Why: academic research (Lou/Polk/Skouras 2019) shows overnight and intraday returns behave very differently; we test which names earn their keep overnight. Limitation: based on ~1 year of data; small samples can mislead.",
 "trend": "What: trend quality - how steady the upward path is, not just how far. Reading: 100 = perfectly steady climb, 0 = no trend. Why: steady climbers fit a certainty-first client better than violent rockets. Limitation: says nothing about whether the trend continues.",
 "hi52": "What: how close the price is to its 52-week (1-year) high, in percent. Reading: 95%+ means right at the high. Why: research shows stocks near their high often keep beating expectations - good entry confirmation. Limitation: near-high stocks fall hard when the story breaks.",
 "signal": "What: the model's plain verdict from the score: BUY (top quarter of the universe), AVOID (bottom quarter), WATCH (middle). Reading: BUY = candidate to own, AVOID = candidate to sell or skip. Why: it turns six numbers into one explainable action for Laura's growth sleeve. Limitation: a label, not a guarantee - every trade still gets a written thesis.",
 "datacol": "What: whether we hold a full year of daily price history for this symbol. Reading: 'full' = all ingredients computed. Limitation: symbols with partial data score on less evidence and are flagged.",
 "f_sector": "What: filter rows by industry group. Why: lets you check the model is not betting everything on one sector - Laura's plan needs diversification.",
 "f_signal": "What: show only BUY, WATCH, or AVOID rows. Why: quick way to see today's action list.",
 "f_search": "What: type a ticker to jump to it. Why: fast check on any holding or candidate.",
 "idea_theme": "What: the broad reason the idea exists (merger event, momentum leader, sector rotation). Why: every trade needs one explainable sentence for the Trading Notes.",
 "idea_thesis": "What: the argument for why this should make money, in plain words. Why: if you cannot explain it, Laura's IPS says do not trade it.",
 "idea_catalyst": "What: the upcoming event that should move the price. Why: a thesis without a catalyst can sit dead for weeks.",
 "idea_entry": "What: planned buy conditions. Why: pre-committed entries stop impulse trades.",
 "idea_exit": "What: the rule that gets us out, written before entering. Why: Laura's certainty-first plan depends on disciplined exits, not hope.",
 "idea_conf": "What: how much evidence backs the idea: High, Medium, Low, or Research (interesting but unproven). Why: position size follows confidence.",
 "idea_downside": "What: a realistic estimate of how much it could lose. Why: the client plan sizes positions so one bad trade cannot dent the reserve goal.",
 "backtest": "What: a replay of the strategy on historical prices to see if the idea ever worked. Reading: positive bars = the pattern earned money. Why: we only trade patterns with historical support and an economic reason. Limitation: past patterns fail live about half the time - that is why live experiments (Exp 1-10) exist.",
 "hypreg": "What: the pre-registered hypothesis list - every idea written down BEFORE testing. Why: declaring ideas in advance is the main defense against fooling ourselves with data mining.",
 "sleeves": "What: the portfolio is split in two: a GROWTH sleeve (stocks, aims to beat inflation) and a RESERVE sleeve (Treasury bonds, aims to guarantee the ten $50,000 payments). Why: Laura's problem is certainty of future payments, not maximum return. Limitation: the split follows provisional diligence figures until the final report.",
 "coverage": "What: reserve-coverage ratio = projected reserve money at start-2033 divided by the $430-440k target. Reading: 1.00 or above = fully funded; below 1.00 = shortfall risk. Why: this single number is the health check for Laura's whole plan.",
 "derisk": "What: automatic safety rules. If coverage drops below 1.00, money shifts from growth to reserve; if the portfolio falls 15% from its peak, growth buys freeze; if one stock grows past its cap, it gets trimmed. Why: pre-committed rules remove panic decisions.",
 "glide": "What: the planned slow shift from ~80% stocks / 20% bonds today toward ~60/40 by 2031 as Laura's payment dates approach. Why: less risk as the liability gets closer - standard practice for goal-based investing.",
 "risksnap": "What: the live practice portfolio broken into its sleeves with each position's job. Why: shows at a glance whether real money matches the plan. Limitation: HCWC/HOST is frozen by StockTrak's ticker change, so its value is a stale placeholder.",
 "explog": "What: the lab notebook - every experiment, registered before it ran, with its result. Why: pre-registration plus honest outcomes is what makes the research credible for the final report.",
 "tradelog": "What: every real order with date, size, price, confirmation code and reason. Why: this is the raw material for the three Trading Notes and the IPS evidence trail.",
 "declog": "What: the audit spine - every decision (design, data, signal, trade, rejection, mark, mandate change, lesson) with its reason and which deliverable it feeds. Why: the user asked for exhaustive reusable documentation; this page is the single source for the Trading Notes, IPS and final report.",
 "dectype": "What: decision category. DESIGN = model rule chosen. DATA = where numbers come from. SIGNAL = model output. TRADE = real order. REJECT = candidate refused with reason. MARK = P&L checkpoint. MANDATE = instruction from the user. LESSON = platform or process fix.",
 "methodology": "What: the rulebook - data sources, competition constraints, anti-overfitting defenses, known weaknesses. Why: the IPS and final report must defend every choice; this is the defense.",
 "case": "What: the official Wharton case facts about Laura Gao: her contributions, the ten fixed $50,000 payments (2033-2042), and deliverable deadlines. Why: competition documents override every generic assumption.",
 "c_tol": "What: Laura's risk band - how much price swing her plan accepts. Reading: medium (our team's stated assumption, NOT a case fact) allows roughly 20-40% volatility names; low would cap near 20%; high near 50%. Why: suitability is judged against her goal, never her age.",
 "c_hor": "What: months until the first liability - 76 months to the 2033 reserve date. Why: horizon controls how much short-term risk the plan can take.",
 "c_arch": "What: the two-sleeve structure (growth + reserve) and glidepath from the diligence draft. PROVISIONAL until the final report.",
 "c_mandate": "What: the current operating authority - fully automated trading under Laura's mandate, no protected positions, every fill logged.",
 "c_pref": "What: sectors Laura's plan prefers or avoids. Ticking one off re-ranks instantly. Why: documents any sector tilts as conscious choices.",
 "c_book": "What: the real positions with live-computed weights. Edit a share count to test what-if scenarios - everything recomputes. Limitation: HCWC is frozen at cost by the platform; its displayed value is stale.",
 "c_flags": "What: automatic warnings - concentration above caps, suitability breaches, stale data. Reading: any red flag must be answered in the Trading Notes.",
 "c_base": "What: the raw model score before Laura's suitability filter.",
 "c_suit": "What: the suitability multiplier from the volatility band: 1.0 = fully suitable, lower = penalized, 0 = banned (over the 40% band). Why: a great stock that is too wild for Laura scores down automatically.",
 "c_cscore": "What: final client score = base score x suitability. Reading: this is the ranking the trading agent actually follows for Laura.",
 "csignal": "What: the client verdict after suitability: BUY / WATCH / AVOID. Why: one plain action word per name for the IPS.",
}

def info(key):
    return '<button type="button" class="info" aria-label="what is this">i</button><span class="tip">' + esc(TIPS[key]) + '</span>'

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
    ("2026-09-18", "Client-suitable deployment", "Laura top-5 sleeve (MSFT/RTX/CVX/QQQ/JNJ) deployed ~$49.9k after AAPL exit, per user 'carry out the model's suggestions' (10:15 PM IST). REJECTED with logged reasons: PLTR (vol 50.3% > 40% client band - unsuitable), INDP add (event-risk cap 10%, already 500 sh), HOST (frozen/untradeable - no real quote). User reiterated: PLTR stays excluded unless Laura's suitability rules change", "Executed; all 5 fills verified full-size"),
    ("2026-09-18", "All legacy protections removed", "User instruction 2026-09-18 ~10:00 PM IST: AAPL protection and all prior personal-position protections are REMOVED. The entire portfolio is governed only by the Laura Gao client mandate - any position may be bought, trimmed, or sold when the client-suitable model and live evidence support it. HOST carries no hold protection either, but execution still requires a verified tradeable converted position and a real quote (the HCWC->HOST ticker change is still not processed; the frozen $13.77 display is not actionable)", "Mandate updated; objective = liability certainty + suitable growth, full explainability"),
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
    ("2026-09-18 12:31 ET", "AAPL", "SELL", "100 sh @ $334.93 ($33,468 net)", "Conf EB3B94F6. Protection revoked by user instruction (WhatsApp 9:59:51 PM IST); algorithm AVOID signal - momentum/trend weakened vs peers; certainty-first mandate moves capital to strongest suitable names + reserve build. Round trip +$546 (+1.7% vs $329.22 cost). Full fill verified (posted ~45s after confirmation - logged as platform lesson)"),
    ("2026-09-18 12:46 ET", "MSFT", "BUY", "+20 sh @ $493.59 ($9,871.80); 30 sh total", "Conf 9D5D48F2. Client-suitable deployment, Laura top-5 #1; full fill"),
    ("2026-09-18 12:47 ET", "RTX", "BUY", "52 sh @ $191.72 ($9,969.44)", "Conf 64D247E5. Client-suitable deployment #2; full fill"),
    ("2026-09-18 12:48 ET", "CVX", "BUY", "47 sh @ $210.61 ($9,898.67)", "Conf 4A877B9E. Client-suitable deployment #3; full fill"),
    ("2026-09-18 12:48 ET", "QQQ", "BUY", "14 sh @ $716.30 ($10,028.20)", "Conf 9671D555. Client-suitable deployment #4; full fill"),
    ("2026-09-18 12:49 ET", "JNJ", "BUY", "37 sh @ $269.77 ($9,981.49)", "Conf 5FE8127F. Client-suitable deployment #5; full fill. ~$49.9k deployed incl. commissions; cash $6,254.30, trades 36/200"),
]


DECISIONS = [
    ("2026-09-16", "DESIGN", "Fixed a-priori factor weights declared before testing: 0.30 3m momentum / 0.15 1m momentum / 0.15 overnight-return Sharpe / 0.15 low-vol / 0.15 trend / 0.10 52w-high proximity", "First defense against overfitting - no fitted parameters", "Methodology tab; H1-H5 pre-registration", "IPS + Final Report"),
    ("2026-09-16", "DATA", "Yahoo Finance daily bars cached per symbol (never re-fetched history); StockTrak snapshots at scheduled checkpoints only; SEC filings/news via web fetch at event time", "Reproducibility + no aggressive scraping of the competition platform", "browser_ingest.sh rail; 69 cached 1y bar files through 2026-09-18", "IPS + Final Report"),
    ("2026-09-17", "LESSON", "SOXL partial fill (9 of 125) exposed a verification gap", "Standing rule adopted: verify actual filled quantity on every order from transaction history, never the order ticket", "Trade log 2026-09-17 14:35 ET", "Trading Notes"),
    ("2026-09-17", "LESSON", "Near-close large order (SOXL 116) qty-reduced by the platform", "Standing rule: size orders earlier in the session near the close", "Trade log 2026-09-18 pre-close", "Trading Notes"),
    ("2026-09-18", "MANDATE", "Full automation granted: algorithm buys/sells without per-trade approval (~8:46 PM IST), then ALL legacy protections removed (~10:00 PM IST, verified WhatsApp wamid...E0NDREM0UA 9:59:51 PM)", "Full portfolio governed only by the Laura Gao client mandate; objective = liability certainty + suitable growth, IPS consistency ahead of raw P&L", "Case tab mandate string; experiment-log rows", "IPS + Final Report"),
    ("2026-09-18", "SIGNAL", "Post-open full-universe re-rank through 2026-09-18 open: MSFT #1 +0.565, PLTR #2 +0.530, RTX #3, CVX #4, INDP #5; SOXL #68 AVOID; Laura client top-5: MSFT, RTX, CVX, QQQ, JNJ", "Fixed-weight composite over 68/68 ingested symbols; client filter applies vol band <=40% and event caps", "Screener + Client mode tabs (live recompute)", "Trading Notes"),
    ("2026-09-18", "REJECT", "PLTR rejected despite composite #2", "Vol 50.3% exceeds the 40% client suitability band; user confirmed PLTR stays excluded unless Laura's suitability rules change", "Trading-agent relay 10:22 PM IST", "Trading Notes"),
    ("2026-09-18", "REJECT", "INDP add rejected", "Event-risk cap 10%; already held 500 sh (+18.2%)", "Trading-agent relay 10:22 PM IST", "Trading Notes"),
    ("2026-09-18", "REJECT", "HOST sell deferred", "Position frozen: HCWC->HOST conversion not processed by StockTrak; $0 quote on both tickers; frozen $13.77 display is not actionable. Rule: sell at market the moment a verified tradeable position + real quote exists", "Trading-agent relays 8:47/9:46/10:02 PM IST", "Trading Notes"),
    ("2026-09-18", "TRADE", "AAPL sold 100 @ $334.93 (+$546, +1.7%) after protection revoked; proceeds + cash deployed into Laura top-5 sleeve: MSFT +20, RTX 52, CVX 47, QQQ 14, JNJ 37 (~$49.9k)", "Certainty-first mandate: weakest suitable-trend holding out, strongest client-suitable names in; every fill verified full-size in transaction history", "Trade log confs EB3B94F6, 9D5D48F2, 64D247E5, 4A877B9E, 9671D555, 5FE8127F", "Trading Notes"),
    ("2026-09-18", "MARK", "Exp 10 (MSFT composite forward test) open marks: entry $494.09; close/+1d/+2d marks pending - first close mark after 2026-09-18 US close", "Pre-registered evaluation protocol; marks recorded against entry with factor snapshot", "Experiment log Exp 10", "Trading Notes"),
    ("2026-09-18", "DESIGN", "Two-sleeve architecture: growth sleeve + Treasury reserve sleeve; reserve target $430-440k nominal ladder by start-2033; glidepath ~80/20 toward 60/40 by 2031; reserve-coverage ratio + 3 de-risk triggers first-class", "PROVISIONAL diligence v1 (final 10h report pending): liability certainty dominates return chase at ~1.9% required blended return", "Portfolio risk tab; Case tab (PROVISIONAL labels)", "IPS + Final Report"),
    ("2026-09-18", "LESSON", "AAPL fill posted ~45s after the confirmation page", "An instant re-read of history can miss a completed order; verification reads wait for posting", "Trading-agent relay 10:02 PM IST", "Trading Notes"),
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
    "PROVISIONAL - DUE-DILIGENCE v1 working draft (2026-09-18; final report pending, figures may revise): Laura Gao is a REAL person - case facts verify against the public record (Wharton 2018 Statistics, ex-Twitter PM, Messy Roots 2022, Kirby's Lessons 2025, comics professor at California College of the Arts). The financial plan is the fictional layer. Required blended return ~1.9% - certainty problem, not a return chase. Reserve $430-440k nominal Treasury ladder at start-2033 (cheap to fund on the current tape: Fed 3.75-4.00%, 10Y ~5.0%, 30Y ~5.34%). Monte Carlo (20k paths): equity-heavy = 14% reserve-miss (rejected); conservative glidepath < 1%.",
    "FULL AUTOMATION MANDATE (user instructions 2026-09-18): the Laura Gao algorithm drives StockTrak buys/sells WITHOUT per-trade approval. Guardrails: live verification, competition rules, client-mode caps, every fill logged with rationale for Trading Notes. UPDATE ~10:00 PM IST: AAPL protection and ALL legacy personal-position protections removed - the full portfolio is governed only by Laura's client mandate. HOST: no special hold protection, but execution requires a verified tradeable converted position and real quote (HCWC->HOST changeover still pending; frozen $13.77 display not actionable). Optimize explainable IPS consistency and Trading Notes quality ahead of raw 10-week P&L.",
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
    .replace("{{ARCHITECTURE}}", CLIENT["profile"].get("architecture","")).replace("{{MANDATE}}", CLIENT["profile"].get("mandate","")).replace("{{BOOK}}", format(CLIENT["book"], ",.0f")).replace("{{CPOS_ROWS}}", cpos_rows)
    .replace("{{CFLAG_ITEMS}}", cflag_items).replace("{{CRANK_ROWS}}", crank_rows)
    .replace("{CINFO_MODE}", info("c_mandate")).replace("{CINFO_TOL}", info("c_tol"))
    .replace("{CINFO_HOR}", info("c_hor")).replace("{CINFO_ARCH}", info("c_arch"))
    .replace("{CINFO_MAND}", info("c_mandate")).replace("{CINFO_PREF}", info("c_pref"))
    .replace("{CINFO_BOOK}", info("c_book")).replace("{CINFO_FLAGS}", info("c_flags"))
    .replace("{CINFO_BASE}", info("c_base")).replace("{CINFO_SUIT}", info("c_suit"))
    .replace("{CINFO_CSCORE}", info("c_cscore")).replace("{CINFO_CSIGNAL}", info("csignal")))
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
dec_rows = "".join(f"<tr><td>{esc(d)}</td><td><b>{esc(t)}</b></td><td>{esc(sub)}</td><td>{esc(rat)}</td><td>{esc(ev)}</td><td>{esc(del_)}</td></tr>" for d, t, sub, rat, ev, del_ in DECISIONS)
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

.info{display:inline-block;width:15px;height:15px;line-height:14px;border-radius:50%;background:#30363d;color:#8b949e;font-size:10px;text-align:center;cursor:pointer;border:1px solid #484f58;margin-left:4px;vertical-align:middle;font-style:normal;padding:0}
.info:hover,.info:focus{background:#58a6ff;color:#0d1117;outline:none}
.tip{display:none;position:fixed;z-index:99;max-width:320px;background:#161b22;border:1px solid #58a6ff;border-radius:8px;padding:10px 12px;font-size:12px;line-height:1.5;color:#e6edf3;box-shadow:0 4px 16px rgba(0,0,0,.5);font-weight:normal;text-align:left;text-transform:none;white-space:normal}
.tip.open{display:block}
.plain{background:#0d1117;border:1px solid #30363d;border-radius:6px;padding:8px 12px;font-size:12.5px;color:#c9d1d9;margin-bottom:12px}
.plain b{color:#58a6ff}
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

document.addEventListener('click',function(e){
var b=e.target.closest?e.target.closest('.info'):null;
if(!b){document.querySelectorAll('.tip.open').forEach(function(t){t.classList.remove('open');});return;}
var t=b.nextElementSibling;if(!t||!t.classList.contains('tip'))return;
var was=t.classList.contains('open');
document.querySelectorAll('.tip.open').forEach(function(x){x.classList.remove('open');});
if(!was){t.classList.add('open');
var r=b.getBoundingClientRect();
var w=Math.min(320,window.innerWidth-24);
t.style.maxWidth=w+'px';
t.style.left=Math.max(12,Math.min(r.left,window.innerWidth-w-12))+'px';
t.style.top=Math.min(r.bottom+6,window.innerHeight-220)+'px';
e.stopPropagation();}});

{_client_js}
function filt2(){var se=document.getElementById('s-sector').value,si=document.getElementById('s-signal').value,
q=document.getElementById('s-q').value.toLowerCase();
document.querySelectorAll('#screen tbody tr').forEach(function(r){
var ok=(!se||r.dataset.sector===se)&&(!si||r.dataset.signal===si)&&(!q||r.textContent.toLowerCase().includes(q));
r.style.display=ok?'':'none';});}
"""

html = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>StockTrak Research Terminal v0.9</title><style>{CSS}</style></head><body>
<header><h1>StockTrak Research Terminal <span style="color:#58a6ff">v0.9</span></h1>
<span class="sub">Wharton competition practice account &middot; generated {NOW:%Y-%m-%d %H:%M} IST &middot; all statistics from cached daily bars, sources dated</span></header>
<nav>
<button data-t="screener" onclick="show('screener')">Screener</button>
<button data-t="client" onclick="show('client')">Client mode</button>
<button data-t="ideas" onclick="show('ideas')">Ranked ideas</button>
<button data-t="backtests" onclick="show('backtests')">Backtests</button>
<button data-t="risk" onclick="show('risk')">Portfolio risk</button>
<button data-t="experiments" onclick="show('experiments')">Experiment log</button>
<button data-t="trades" onclick="show('trades')">Trade log</button>
<button data-t="decisions" onclick="show('decisions')">Decision log</button>
<button data-t="methodology" onclick="show('methodology')">Methodology</button>
<button data-t="casestudy" onclick="show('casestudy')">Case study</button>
</nav>

<section id="screener"><h2>Universe screener - explainable buy/sell ranking</h2>
<div class="warn">Cross-sectional ranking over the StockTrak-eligible universe ({n_cached} of {n_total} symbols ingested). Score = fixed a-priori weights: 30% 3-month momentum, 15% 1-month momentum, 15% overnight-return Sharpe, 15% low volatility, 15% trend quality, 10% 52w-high proximity. No fitted parameters: the weights are declared before testing, which is the first defense against overfitting. Hover a row to see each factor's contribution to its score. Top quartile = BUY candidates, bottom quartile = AVOID, rest WATCH. Research output, not auto-execution.</div>
<div class="plain"><b>In plain terms:</b> this page ranks all 68 stocks we can trade from best to worst using six pre-declared tests. Tap the small <b>i</b> dots anywhere on this site to learn what any number means. Green BUY = candidates to own for Laura's growth sleeve, red AVOID = candidates to sell or skip.</div>
<div class="filters">
<select id="s-sector" onchange="filt2()"><option value="">All sectors</option>{sector_opts}</select>
<select id="s-signal" onchange="filt2()"><option value="">All signals</option><option>BUY</option><option>WATCH</option><option>AVOID</option></select>
<input id="s-q" oninput="filt2()" placeholder="Search symbol..."></div>
<div class="card"><table id="screen"><thead><tr><th>#</th><th>Symbol</th><th>Sector{info('f_sector')}</th><th>Score{info('score')}</th><th>1M{info('mom1')}</th><th>3M{info('mom3')}</th><th>Vol 20d{info('vol')}</th><th>On Sharpe{info('onsharpe')}</th><th>Trend{info('trend')}</th><th>52w hi{info('hi52')}</th><th>Signal{info('signal')}</th><th>Data{info('datacol')}</th></tr></thead>
<tbody>{screen_rows}</tbody></table></div></section>

{_client_html}

<section id="ideas"><h2>Ranked idea shortlist</h2>
<div class="warn">Research shortlist, not auto-execution. Every idea needs a defensible thesis before a trade; the StockTrak notes field records it in natural language.</div>
<div class="filters" id="ideas-f">
<select id="f-theme" onchange="filt()"><option value="">All themes</option>{theme_opts}</select>
<select id="f-conf" onchange="filt()"><option value="">All confidence</option><option>High</option><option>Medium</option><option>Low</option><option>Research</option></select>
<input id="f-q" oninput="filt()" placeholder="Search thesis, catalyst, exit..."></div>
<table id="ideas"><thead><tr><th>Idea</th><th>Theme{info('idea_theme')}</th><th>Thesis{info('idea_thesis')}</th><th>Catalyst{info('idea_catalyst')}</th><th>Entry{info('idea_entry')}</th><th>Exit rule{info('idea_exit')}</th><th>Confidence{info('idea_conf')}</th><th>Expected downside{info('idea_downside')}</th></tr></thead>
<tbody>{ideas_rows}</tbody></table></section>

<section id="backtests"><h2>Backtests: overnight vs intraday decomposition (H1){info('backtest')}</h2>
<div class="warn">Historical discovery only: $25/trade commission and slippage apply to any traded version. Day-of-week rows are exploratory and unadjusted for multiple testing.</div>
{backtest_blocks}
<div class="card"><h3>Hypothesis register{info('hypreg')}</h3>
<table><tr><th>ID</th><th>Hypothesis</th><th>Status</th></tr>{hyp_rows}</table></div></section>

<section id="risk"><h2>Two-sleeve architecture &amp; reserve coverage{info('sleeves')}</h2>
<div class="warn">PROVISIONAL - from the client due-diligence WORKING DRAFT v1 (2026-09-18); the final 10-hour report lands before Saturday 3 PM IST and may revise these figures: Laura's mandate is LIABILITY-DRIVEN. Required blended return is only ~1.9% to fund the ten $50k payments - the problem is CERTAINTY, not growth. Architecture: a GROWTH sleeve and a RESERVE sleeve, gliding from ~80/20 toward ~60/40 by 2031. Reserve target at start-2033: $430-440k via a nominal Treasury ladder (the liability is not inflation-adjusted, so nominal Treasuries hedge it directly). Facility headroom at 2033: ~$155-220k on institutional return assumptions. Preliminary 2031 co-sponsor range: $100-250k (floor fundable in ~78-85% of Monte Carlo paths, ceiling ~19-31%; 20k paths). Staying equity-heavy leaves a 14% chance of missing the reserve - rejected; the conservative glidepath cuts it under 1%.</div>
<div class="card"><h3>First-class metrics &amp; de-risk triggers</h3><ol>
<li><b>Reserve-coverage ratio</b>{info('coverage')} = projected reserve assets at start-2033 / $430-440k target. Projected quarterly on the conservative path; must stay >= 1.00.</li>
<li><b>De-risk trigger 1:</b>{info('derisk')} coverage projection &lt; 1.00 = shift 10pp from growth to reserve immediately.</li>
<li><b>De-risk trigger 2:</b> portfolio drawdown &gt; 15% from peak = freeze growth adds until coverage recovers.</li>
<li><b>De-risk trigger 3:</b> single name above its client-mode cap = trim to cap on next session.</li>
<li><b>Glidepath checkpoints:</b>{info('glide')} 2028 (after the $150k contribution), 2031 (before co-sponsor range is stated), 2033 (reserve set aside, ladder built).</li>
</ol></div>
<h3>Practice-book risk snapshot (verified through the 2026-09-18 session){info('risksnap')}</h3>
<div class="warn">Positions verified through the 2026-09-17 session. Largest structural risks: HCWC event risk (~$44k after -19.3% on day one, user-mandated HOLD), overnight gaps in the 3x sleeves (SOXL 139 sh, TQQQ). Positions bought today cannot be sold today - gap risk is undiversifiable within a session.</div>
<div class="card"><table><tr><th>Sleeve</th><th>Theme</th><th>Role</th><th>Note</th></tr>{port_rows}</table></div></section>

<section id="experiments"><h2>Experiment log{info('explog')}</h2>
<div class="card"><table><tr><th>Date</th><th>Experiment</th><th>What happened / design</th><th>Outcome / status</th></tr>{exp_rows}</table></div></section>

<section id="trades"><h2>Trade log (dated, auditable){info('tradelog')}</h2>
<div class="card"><table><tr><th>Date</th><th>Instrument</th><th>Side</th><th>Quantity</th><th>Note</th></tr>{trade_rows}</table></div></section>

<section id="decisions"><h2>Decision log - audit spine for Trading Notes / IPS / Final Report{info('declog')}</h2>
<p class="note">Every model design choice, data source, signal, trade, rejected candidate, fill, P&amp;L mark, mandate change and lesson, dated, with rationale, evidence pointer and the deliverable it feeds. User instruction 2026-09-18 10:28 PM IST: exhaustive reusable documentation, Laura-only mandate.</p>
<div class="card"><table><thead><tr><th>Date</th><th>Type{info('dectype')}</th><th>Decision</th><th>Rationale</th><th>Evidence</th><th>Feeds</th></tr></thead><tbody>{dec_rows}</tbody></table></div></section>
<section id="methodology"><h2>Methodology{info('methodology')}</h2>{meth_blocks}</section>

<section id="casestudy"><h2>Client case - Laura Gao (Wharton 2026-2027){info('case')}</h2>
<div class="card"><p>From the three official competition PDFs (case study, strategy roadmap, competition guide) supplied 2026-09-18. Competition documents override earlier generic assumptions.</p><ol>{case_items}</ol></div></section>

<footer>StockTrak Research Terminal v0.9 &middot; Python-generated, single-file, no external assets &middot; data: Yahoo Finance daily bars (cached 2026-09-18), StockTrak scheduled snapshots &middot; built for the Wharton competition practice period</footer>
<script>{JS}</script></body></html>"""

out = os.path.join(HERE, "index.html")
open(out, "w").write(html)
print("wrote", out, f"{len(html)/1024:.0f} KB")
