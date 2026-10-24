#!/usr/bin/env python3
"""research_engine.py - deterministic fundamentals research engine.

WHAT THIS IS:
- Pulls company-reported financial facts from SEC EDGAR XBRL company-concept
  endpoints (public US government data), using ordered tag fallbacks per metric.
- Computes a fixed-rule scorecard (growth, margins, leverage, cash flow) with
  a citation (concept, period, accession number) for every number.
- Fail-closed: insufficient data, stale filings, or stale metric facts
  (latest period end older than ~2 years) produce explicit statuses/flags
  and exclusion from scoring, never a guessed score.

WHAT THIS IS NOT:
- Not an AI model, not a price predictor, not a recommendation to buy or sell.
- The scorecard is a set of fixed heuristics for organizing evidence. Judgment
  and every trade decision belong to the human reviewer.
- Not comprehensive news/filings coverage: the only event signal is the latest
  filing date derived from concept metadata.

Runtime model: agent-run on a schedule. The engine reads concept JSON from a
local cache dir (fetched separately and gently, honoring SEC fair access) or
can fetch directly with a declared User-Agent on networks where SEC allows it.
Holdings/config stay OUT of the public repo; this file is generic.

Stdlib only. Python 3.8+.
"""

import argparse
import datetime as dt
import json
import os
import sys
import time
import urllib.request

USER_AGENT = "StudentResearchProject/1.0 (aaditya44@users.noreply.github.com)"
SEC_BASE = "https://data.sec.gov/api/xbrl/companyconcept/CIK{cik}/{tax}/{tag}.json"
ANNUAL_FORMS = {"10-K", "10-K/A", "20-F", "20-F/A", "40-F", "40-F/A"}
MIN_ANNUAL_DAYS = 300
STALE_FILING_DAYS = 400
# Metric facts whose latest period end is older than this are excluded from
# scoring: an 11-year-old debt figure says nothing about current leverage.
METRIC_STALE_DAYS = 731

# Ordered fallbacks per metric: first tag with usable current annual data wins.
TAG_FALLBACKS = {
    "revenue": [
        ("us-gaap", "RevenueFromContractWithCustomerExcludingAssessedTax"),
        ("us-gaap", "RevenueFromContractWithCustomerIncludingAssessedTax"),
        ("us-gaap", "Revenues"),
        ("us-gaap", "SalesRevenueNet"),
        ("ifrs-full", "Revenue"),
    ],
    "operating_income": [
        ("us-gaap", "OperatingIncomeLoss"),
        ("ifrs-full", "ProfitLoss"),
    ],
    "net_income": [
        ("us-gaap", "NetIncomeLoss"),
        ("us-gaap", "ProfitLoss"),
        ("ifrs-full", "ProfitLoss"),
    ],
    "operating_cash_flow": [
        ("us-gaap", "NetCashProvidedByUsedInOperatingActivities"),
        ("ifrs-full", "CashFlowsFromUsedInOperatingActivities"),
    ],
    "long_term_debt": [
        ("us-gaap", "LongTermDebt"),
        ("us-gaap", "LongTermDebtNoncurrent"),
        ("us-gaap", "LongTermDebtAndCapitalLeaseObligations"),
        ("ifrs-full", "NoncurrentBorrowings"),
    ],
    "equity": [
        ("us-gaap", "StockholdersEquity"),
        ("us-gaap", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"),
        ("ifrs-full", "Equity"),
    ],
    "cash": [
        ("us-gaap", "CashAndCashEquivalentsAtCarryingValue"),
        ("ifrs-full", "CashAndCashEquivalents"),
    ],
}

CORE_METRICS = ["revenue", "operating_income", "net_income",
                "operating_cash_flow", "long_term_debt", "equity"]
INSTANT_METRICS = {"long_term_debt", "equity", "cash"}


def _parse_date(s):
    return dt.date.fromisoformat(s)


def annual_series(concept_json):
    """Return annual (fp=FY, ~1-year duration) points deduped by end date,
    keeping the latest-filed per end date, sorted by end ascending."""
    units = concept_json.get("units", {})
    if "USD" in units:
        points = units["USD"]
    else:
        points = next(iter(units.values()), [])
    by_end = {}
    for p in points:
        if p.get("fp") != "FY" or p.get("form") not in ANNUAL_FORMS:
            continue
        if not p.get("start") or not p.get("end") or p.get("val") is None:
            continue
        try:
            dur = (_parse_date(p["end"]) - _parse_date(p["start"])).days
        except Exception:
            continue
        if dur < MIN_ANNUAL_DAYS:
            continue
        cur = by_end.get(p["end"])
        if cur is None or p.get("filed", "") > cur.get("filed", ""):
            by_end[p["end"]] = p
    return [by_end[k] for k in sorted(by_end)]


def instant_series(concept_json):
    """Balance-sheet (instant) facts: no start date, no duration check.
    Keep FY-form points deduped by end date (latest filed), sorted ascending."""
    units = concept_json.get("units", {})
    if "USD" in units:
        points = units["USD"]
    else:
        points = next(iter(units.values()), [])
    instant_forms = ANNUAL_FORMS | {"10-Q", "10-Q/A"}
    by_end = {}
    for p in points:
        if p.get("form") not in instant_forms or not p.get("end") or p.get("val") is None:
            continue
        cur = by_end.get(p["end"])
        if cur is None or p.get("filed", "") > cur.get("filed", ""):
            by_end[p["end"]] = p
    return [by_end[k] for k in sorted(by_end)]


def latest_point(series):
    return series[-1] if series else None


def cagr(series, min_years=2, lookback_points=5):
    """CAGR across the last `lookback_points` annual points. Returns
    (cagr, start_end, end_end) or (None, None, None) when not computable."""
    pts = series[-lookback_points:]
    if len(pts) < 2:
        return None, None, None
    first, last = pts[0], pts[-1]
    try:
        days = (_parse_date(last["end"]) - _parse_date(first["end"])).days
        year_span = _parse_date(last["end"]).year - _parse_date(first["end"]).year
    except Exception:
        return None, None, None
    if year_span < min_years or first["val"] <= 0 or last["val"] is None:
        return None, None, None
    years = days / 365.25
    return (last["val"] / first["val"]) ** (1.0 / years) - 1.0, first["end"], last["end"]


def value_at_end(series, end):
    for p in series:
        if p.get("end") == end:
            return p
    return None


class ConceptSource:
    """Reads concept JSON from a cache dir; optionally fetches missing ones."""

    def __init__(self, cache_dir, allow_fetch=False, sleep_s=2.0):
        self.cache_dir = cache_dir
        self.allow_fetch = allow_fetch
        self.sleep_s = sleep_s
        self.fetch_log = []

    def _path(self, cik, tax, tag):
        return os.path.join(self.cache_dir, f"{cik}_{tax}_{tag}.json")

    def get(self, cik, tax, tag):
        path = self._path(cik, tax, tag)
        if os.path.exists(path):
            with open(path) as f:
                return json.load(f), "cache"
        if not self.allow_fetch:
            return None, "missing"
        url = SEC_BASE.format(cik=cik, tax=tax, tag=tag)
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                body = r.read()
            status = 200
        except Exception as e:  # fail closed, never retry-storm
            self.fetch_log.append({"url": url, "status": getattr(e, "code", None), "error": str(e)[:120]})
            return None, "fetch_error"
        time.sleep(self.sleep_s)
        self.fetch_log.append({"url": url, "status": status, "bytes": len(body)})
        os.makedirs(self.cache_dir, exist_ok=True)
        with open(path, "wb") as f:
            f.write(body)
        return json.loads(body), "fetched"


def pick_metric(source, cik, metric):
    """Try ordered tag fallbacks; return (series, citation) for the first tag
    whose latest annual end date is current enough to be usable, preferring
    the tag with the most recent data. Fail closed with (None, reason)."""
    best = None  # (latest_end, series, citation)
    tried = []
    for tax, tag in TAG_FALLBACKS[metric]:
        cj, how = source.get(cik, tax, tag)
        if not cj:
            tried.append(f"{tax}/{tag}: {how}")
            continue
        builder = instant_series if metric in INSTANT_METRICS else annual_series
        series = builder(cj)
        if not series:
            tried.append(f"{tax}/{tag}: no usable points")
            continue
        end = series[-1]["end"]
        cit = {"taxonomy": tax, "tag": tag, "concept_label": cj.get("label"),
               "accn": series[-1].get("accn"), "end": end, "filed": series[-1].get("filed")}
        if best is None or end > best[0]:
            best = (end, series, cit)
        tried.append(f"{tax}/{tag}: {len(series)} annual pts, latest {end}")
    if best is None:
        return None, {"metric": metric, "tried": tried}
    return {"series": best[1], "citation": best[2], "tried": tried}, None


def score_company(source, cik, name, today=None):
    today = today or dt.date.today()
    out = {"cik": cik, "name": name, "as_of": today.isoformat(),
           "metrics": {}, "flags": [], "score": None, "band": None,
           "status": "OK", "latest_filing_date": None}
    metrics = {}
    latest_filed = None
    for metric in CORE_METRICS + ["cash"]:
        res, err = pick_metric(source, cik, metric)
        if err:
            note = err['tried'][-1] if err['tried'] else 'n/a'
            extra = " (no standard debt concept filed - NOT evidence of zero debt)" if metric == "long_term_debt" else ""
            out["flags"].append(f"missing metric {metric}: {note}{extra}")
            continue
        metrics[metric] = res
        f = res["citation"].get("filed")
        if f and (latest_filed is None or f > latest_filed):
            latest_filed = f
    out["latest_filing_date"] = latest_filed
    present = [m for m in CORE_METRICS if m in metrics]
    if len(present) < 4:
        out["status"] = "INSUFFICIENT_DATA"
        out["flags"].append(f"only {len(present)}/6 core metrics available - not scored")
        return out
    if latest_filed:
        try:
            age = (today - dt.date.fromisoformat(latest_filed)).days
            if age > STALE_FILING_DAYS:
                out["status"] = "NOT_CURRENT"
                out["flags"].append(f"latest filing {latest_filed} is {age}d old - stale")
                return out
        except Exception:
            pass

    # Staleness gate: exclude any metric whose latest point is too old to say
    # anything about the company today (incomplete retrievals, tag migrations
    # and abandoned tags all surface this way). Fail closed, never guess.
    for metric in list(metrics):
        lp = latest_point(metrics[metric].get("series", []))
        if not lp:
            continue
        try:
            age = (today - dt.date.fromisoformat(lp["end"])).days
        except Exception:
            continue
        if age > METRIC_STALE_DAYS:
            out["flags"].append(
                f"stale metric {metric}: latest {lp['end']} is {age}d old - excluded from scoring")
            del metrics[metric]
    if len([m for m in CORE_METRICS if m in metrics]) < 4:
        out["status"] = "INSUFFICIENT_DATA"
        out["flags"].append("fewer than 4 current core metrics after stale-metric exclusion - not scored")
        return out

    ends = []
    for mm in metrics.values():
        lp = latest_point(mm.get("series", []))
        if lp:
            ends.append(lp["end"])
    if len(ends) >= 2:
        try:
            span = (dt.date.fromisoformat(max(ends)) - dt.date.fromisoformat(min(ends))).days
            if span > 731:
                out["flags"].append(f"metric vintages span {span}d ({min(ends)}..{max(ends)}) - mixed-period evidence")
        except Exception:
            pass

    # Derived values with same-period matching only.
    rev = metrics.get("revenue", {}).get("series", [])
    g, g_start, g_end = cagr(rev)
    m = {"revenue_cagr": {"value": g, "start_end": g_start, "end_end": g_end,
                          "citation": metrics.get("revenue", {}).get("citation")}}

    rev_latest = latest_point(rev)
    op_latest = latest_point(metrics.get("operating_income", {}).get("series", []))
    ni_latest = latest_point(metrics.get("net_income", {}).get("series", []))
    if rev_latest and op_latest:
        op_same = value_at_end(metrics["operating_income"]["series"], rev_latest["end"])
        if op_same and rev_latest["val"]:
            m["operating_margin"] = {"value": op_same["val"] / rev_latest["val"], "end": rev_latest["end"]}
        else:
            out["flags"].append("operating margin skipped: no same-period operating income")
    if rev_latest and ni_latest:
        ni_same = value_at_end(metrics["net_income"]["series"], rev_latest["end"])
        if ni_same and rev_latest["val"]:
            m["net_margin"] = {"value": ni_same["val"] / rev_latest["val"], "end": rev_latest["end"]}
        else:
            out["flags"].append("net margin skipped: no same-period net income")

    debt_latest = latest_point(metrics.get("long_term_debt", {}).get("series", []))
    eq_latest = latest_point(metrics.get("equity", {}).get("series", []))
    if debt_latest and eq_latest:
        eq_same = value_at_end(metrics["equity"]["series"], debt_latest["end"]) or eq_latest
        if eq_same["val"] <= 0:
            out["flags"].append("negative equity - debt/equity not meaningful")
        else:
            m["debt_to_equity"] = {"value": debt_latest["val"] / eq_same["val"], "end": debt_latest["end"]}

    ocf_series = metrics.get("operating_cash_flow", {}).get("series", [])
    ocf5 = ocf_series[-5:]
    if len(ocf5) >= 3:
        pos = sum(1 for p in ocf5 if p.get("val", 0) > 0)
        m["ocf_positive_years"] = {"value": pos, "window": len(ocf5)}
    else:
        out["flags"].append("fewer than 3 annual operating-cash-flow points")

    out["metrics"] = m

    # Fixed-rule scorecard. Every rule is stated in the brief with its numbers.
    rules = []
    def add(rule, points):
        rules.append({"rule": rule, "points": points})

    if m.get("revenue_cagr", {}).get("value") is not None:
        g = m["revenue_cagr"]["value"]
        add(f"revenue CAGR {g_start}..{g_end} = {g:.1%} (>=5%:2, 0-5%:1, <0:0)",
            2 if g >= 0.05 else (1 if g >= 0 else 0))
    if m.get("operating_margin", {}).get("value") is not None:
        v = m["operating_margin"]["value"]
        add(f"operating margin {m['operating_margin']['end']} = {v:.1%} (>=15%:2, 5-15%:1, <5%:0)",
            2 if v >= 0.15 else (1 if v >= 0.05 else 0))
    if m.get("net_margin", {}).get("value") is not None:
        v = m["net_margin"]["value"]
        add(f"net margin {m['net_margin']['end']} = {v:.1%} (>0:1 else 0)", 1 if v > 0 else 0)
    if m.get("debt_to_equity", {}).get("value") is not None:
        v = m["debt_to_equity"]["value"]
        add(f"debt/equity {m['debt_to_equity']['end']} = {v:.2f} (<=0.5:2, <=1.5:1, >1.5:0)",
            2 if v <= 0.5 else (1 if v <= 1.5 else 0))
    if m.get("ocf_positive_years", {}).get("value") is not None:
        v = m["ocf_positive_years"]
        add(f"positive operating cash flow {v['value']}/{v['window']} recent FY (all:2, 3-4:1 else 0)",
            2 if v["value"] == v["window"] else (1 if v["value"] >= 3 else 0))

    if len(rules) < 4:
        out["status"] = "INSUFFICIENT_DATA"
        out["flags"].append(f"only {len(rules)} scoreable criteria - not scored")
        return out
    total = sum(r["points"] for r in rules)
    out["score"] = total
    out["score_rules"] = rules
    out["band"] = "strong" if total >= 8 else ("adequate" if total >= 5 else "weak")
    return out


def render_md(res):
    L = []
    L.append(f"# Research brief - {res['name']} (CIK {res['cik']})")
    L.append(f"As of {res['as_of']} | status: {res['status']}"
             + (f" | score {res['score']} ({res['band']})" if res["score"] is not None else ""))
    L.append("")
    L.append("Deterministic rule score from SEC-filed facts. Not a prediction or a recommendation.")
    L.append("")
    if res.get("score_rules"):
        L.append("## Scorecard")
        for r in res["score_rules"]:
            L.append(f"- {r['rule']} -> {r['points']} pts")
        L.append("")
    if res.get("metrics"):
        L.append("## Metrics (company-reported)")
        for k, v in res["metrics"].items():
            cit = v.get("citation") or {}
            cite = f" [{cit.get('taxonomy')}/{cit.get('tag')}, period end {cit.get('end')}, accn {cit.get('accn')}]" if cit else ""
            val = v.get("value")
            vs = f"{val:.4f}" if isinstance(val, float) else str(val)
            L.append(f"- {k}: {vs} (end {v.get('end') or v.get('end_end')}){cite}")
        L.append("")
    if res.get("flags"):
        L.append("## Flags")
        for f in res["flags"]:
            L.append(f"- {f}")
        L.append("")
    L.append(f"Latest filing date (from concept metadata; not comprehensive news coverage): {res.get('latest_filing_date')}")
    return "\n".join(L) + "\n"


def main():
    ap = argparse.ArgumentParser(description="Deterministic SEC fundamentals research engine (not AI, not advice).")
    ap.add_argument("--config", required=True, help="Private JSON: [{\"ticker\":..,\"cik\":..,\"name\":..}, ...]")
    ap.add_argument("--cache-dir", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--fetch", action="store_true", help="Fetch missing concepts directly (declared UA, fair access).")
    ap.add_argument("--sleep", type=float, default=2.0)
    args = ap.parse_args()

    with open(args.config) as f:
        companies = json.load(f)
    src = ConceptSource(args.cache_dir, allow_fetch=args.fetch, sleep_s=args.sleep)
    os.makedirs(args.out, exist_ok=True)
    results = []
    for c in companies:
        cik = str(c["cik"]).zfill(10)
        res = score_company(src, cik, c.get("name") or c.get("ticker") or cik)
        res["ticker"] = c.get("ticker")
        results.append(res)
        with open(os.path.join(args.out, f"{c.get('ticker', cik)}.md"), "w") as f:
            f.write(render_md(res))
    with open(os.path.join(args.out, "summary.json"), "w") as f:
        json.dump({"as_of": dt.date.today().isoformat(), "results": results,
                   "fetch_log": src.fetch_log}, f, indent=2)
    ok = sum(1 for r in results if r["status"] == "OK")
    print(f"scored {ok}/{len(results)} companies OK; summary at {args.out}/summary.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
