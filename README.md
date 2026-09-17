# StockTrak Research System v0.1

Explainable research pipeline for the Wharton/StockTrak competition practice account.

## What exists now (verified running 2026-09-18)
- `overnight_decomp.py` - fetches daily bars, decomposes overnight vs intraday returns, caches every pull. Ran live: AAPL + ^GSPC, 252 bars each.
- `build_site.py` - generates `index.html`: ranked ideas (filterable), backtests with equity curves, portfolio risk, experiment log, trade log, methodology, case-study skeleton. Single self-contained file, no external assets.
- `data/` - cached bars + computed stats (CSV).

## Data sources (tested 2026-09-18)
- Yahoo Finance chart API via agent fetch path. Per-symbol availability is inconsistent (several ETFs blocked); mitigations: cache-on-success, retry/backoff, StockTrak scheduled snapshots as fallback.
- Direct sandbox curl to Yahoo/Stooq/EDGAR is edge-blocked; ingestion goes through the fetch tool or the logged-in browser at checkpoint cadence only.

## Competition constraints encoded
$25 commission/trade, no shorts, no margin, no same-day exits. Practice resets 2026-09-25 16:00 ET; competition starts 2026-09-28 09:30 ET.

## Anti-overfitting
Pre-registered hypotheses (H1-H5), train/validation split + walk-forward, multiple-testing control, min n=30 per cell, max 2-3 parameters per rule, $25 commission + slippage haircut in every backtest, half-sample survival check.

## Roadmap
- Phase 1 (this weekend): broaden symbol ingestion, fill ETF gap via fallback paths, run H1-H3 across the universe.
- Phase 2 (competition week 1): nightly feature assembly from trading-agent checkpoints, weekly walk-forward findings brief.
- Phase 3: validated findings become sizing/timing suggestions in the pre-open brief. Never opaque auto-trading.
