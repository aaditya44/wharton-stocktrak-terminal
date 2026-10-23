# Research engine (scripts/research_engine.py)

Deterministic fundamentals research over SEC EDGAR XBRL company-reported facts.

## What it is
- Pulls per-concept annual series (revenue, operating income, net income,
  operating cash flow, long-term debt, equity, cash) using ordered tag
  fallbacks (companies migrate tags, e.g. `Revenues` ->
  `RevenueFromContractWithCustomerExcludingAssessedTax`; foreign private
  issuers file under `ifrs-full`).
- Computes fixed-rule scores with a citation (concept, period, accession
  number) for every number.
- Fail-closed: fewer than 4 of 6 core metrics -> `INSUFFICIENT_DATA`;
  latest filing older than 400 days -> `NOT_CURRENT`. No score is emitted
  in either case.
- Same-period matching only: margins are computed from identical period
  end dates, never mixed periods.

## What it is not
- Not an AI model, not a price predictor, not investment advice, not a
  recommendation to buy or sell anything. Scores organize evidence for a
  human reviewer who makes every decision.
- Not news coverage: the only event signal is the latest filing date from
  concept metadata.
- Not an unattended service: it is run by an agent on a schedule, with
  agent review of output before anything is shared.

## Runtime model
- Code lives here (generic). Private inputs (ticker lists, thresholds) and
  outputs never live in this repo.
- Data fetching honors SEC fair access: declared User-Agent, low request
  counts, spaced calls, no retrying against blocks. The agent fetches
  concept JSON into a cache dir separately; the engine reads the cache
  (`--fetch` direct mode exists only for networks where SEC permits it).
- GitHub Actions runners are currently blocked by SEC (403 from CI IPs):
  do not add a workflow that fetches from SEC until that is re-verified.

## Validate
    python3 -m unittest discover -s tests

## Run
    python3 scripts/research_engine.py --config private_config.json \
        --cache-dir cache --out out
