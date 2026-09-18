#!/usr/bin/env python3
"""client.py - explainable client-suitability layer.

Declared rules, not fitted parameters. A profile maps to a volatility band and
concentration caps; each ranked symbol gets a suitability multiplier from how
its realized vol sits against the band, plus a small sector-preference tilt.
Portfolio diagnostics produce concentration/allocation flags. Suitability is
NEVER inferred from age alone: the profile's stated tolerance, horizon,
liquidity and constraints drive everything; uncertainty is preserved in flags.
"""
import json, os

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")

RULES = {
  "high":   {"vol_band": 40, "single_name_cap": 15, "leveraged_cap": 15, "event_cap": 10},
  "medium": {"vol_band": 25, "single_name_cap": 10, "leveraged_cap": 5,  "event_cap": 5},
  "low":    {"vol_band": 15, "single_name_cap": 7,  "leveraged_cap": 0,  "event_cap": 5},
}

PROFILE = {  # LAURA GAO - the assigned Wharton client (case study PDF, 2026-09-18). Competition documents override prior generic assumptions.
  "client_name": "Laura Gao (assigned competition client)",
  "life_stage": "author, illustrator, entrepreneur, educator (Wharton Statistics 2018; ex-tech PM)",
  "goal": "Fund ten annual $50k residency operating payments 2033-2042 with high certainty (operating reserve), then a responsible 2033 facility contribution, preserving flexibility",
  "horizon_months": 76,
  "risk_tolerance": "medium",
  "liquidity_need": "none until 2033 (living expenses covered outside portfolio); then $50k/yr fixed 2033-2042",
  "constraints": "Case: $300k start-2027 + $150k start-2028, no other flows before 2033. Practice book rules: $25/trade, no shorts, no margin, no same-day exits. AAPL protected core holding (user instruction 2026-09-18). ASSUMPTION (team judgment, not case fact): her stated 'balance between growth and protecting capital for goals' maps to the medium band; her exact risk capacity/tolerance split is an open research item for the due-diligence report.",
  "sector_preferences": ["IndexETF", "Technology"],
}

# Verified practice-book positions (feeds through 2026-09-18 20:10 IST; SOXL exited 10:00 ET).
# Also held but not scored here: 50 units UST 2.750% 02/15/2028 (~$48,712, -0.14%; IEF/GOVT/TLT proxies neutral - HOLD)
# and ~$22,686 cash after the SOXL exit. Counts unknown for older sleeves are flagged, not invented.
HOLDINGS = [
  {"symbol": "HCWC", "shares": 4000, "note": "merger closed; ticker change HCWC->HOST pending on StockTrak, price frozen at cost; conditional exit armed"},
  {"symbol": "NVDA", "shares": 205},
  {"symbol": "INDP", "shares": 500},
  {"symbol": "INTC", "shares": 50},
  {"symbol": "MSFT", "shares": 10, "note": "Exp 10 forward test, entered 09-18 @ $494.09, conf A50BD22B"},
]

def load(sym):
    p = os.path.join(DATA, f"bars_{sym.replace('^','I_').replace('=','_')}_1y.json")
    return json.load(open(p)) if os.path.exists(p) else None

def last_close(sym):
    rows = load(sym)
    return rows[-1][2] if rows else None

def compute():
    rules = RULES[PROFILE["risk_tolerance"]]
    ranking = json.load(open(os.path.join(DATA, "ranking.json")))
    by_sym = {r["symbol"]: r for r in ranking}

    # suitability multiplier per symbol
    for r in ranking:
        band = rules["vol_band"]
        if r["vol20"] <= band: mult, note = 1.0, "inside vol band"
        elif r["vol20"] <= band*1.5: mult, note = 0.6, "above band (capped)"
        else: mult, note = 0.2, "well outside band"
        if r["sector"] in PROFILE["sector_preferences"]:
            mult = min(1.0, mult + 0.10)
            note += "; preferred sector"
        r["suit_mult"] = round(mult, 2)
        r["suit_note"] = note
        r["client_score"] = round(r["score"] * mult + (0.05 if r["sector"] in PROFILE["sector_preferences"] else 0), 3)
    client_ranking = sorted(ranking, key=lambda r: -r["client_score"])
    for i, r in enumerate(client_ranking): r["client_rank"] = i + 1

    # portfolio diagnostics over verified positions
    book = 291889.07  # verified 09-18 close ET; cash $10,348.44; 28/200 trades
    positions, total_verified = [], 0.0
    for h in HOLDINGS:
        px = last_close(h["symbol"])
        if not px: continue
        val = h["shares"] * px
        total_verified += val
        positions.append({**h, "price": round(px, 2), "value": round(val), "weight": round(val/book*100, 1)})
    positions.sort(key=lambda p: -p["value"])

    flags = []
    for p in positions:
        sec = by_sym.get(p["symbol"], {}).get("sector", "")
        if p["weight"] > rules["single_name_cap"]:
            flags.append(f"{p['symbol']} is ~{p['weight']}% of book - above the {rules['single_name_cap']}% single-name cap for a {PROFILE['risk_tolerance']}-tolerance profile")
        if sec == "LeveragedETF":
            flags.append(f"{p['symbol']} is a 3x leveraged ETF at ~{p['weight']}% of book - leveraged sleeve cap is {rules['leveraged_cap']}%")
        if sec == "EventDriven" and p["weight"] > rules["event_cap"]:
            flags.append(f"{p['symbol']} event-driven position ~{p['weight']}% of book exceeds the {rules['event_cap']}% event cap; gap risk is binary")
    if PROFILE["horizon_months"] <= 3:
        flags.append("Horizon is ~10 weeks: error tolerance is compressed - prefer liquid names and pre-defined exits over positions that need time to work")
    flags.append(f"Verified positions cover ${total_verified:,.0f} of a ${book:,.0f} book; unverified sleeves (UUP/GLD/TQQQ/AAPL/XLE/ITA/LMT/TLT/Treasury) are excluded from concentration math - confirm exact counts in StockTrak")
    flags.append("Indicative analysis for a simulated competition account, not personalized financial advice; suitability follows the stated profile, never age alone")

    out = {"profile": PROFILE, "rules": rules, "book": book,
           "positions": positions, "flags": flags, "client_ranking": client_ranking}
    json.dump(out, open(os.path.join(DATA, "client.json"), "w"), indent=1)
    return out

if __name__ == "__main__":
    c = compute()
    print(f"{len(c['client_ranking'])} client-ranked; {len(c['flags'])} flags")
    for f in c["flags"]: print(" -", f)
    for r in c["client_ranking"][:5]:
        print(f"  #{r['client_rank']} {r['symbol']:>5} client={r['client_score']:+.3f} (base {r['score']:+.3f} x{r['suit_mult']}) {r['suit_note']}")
