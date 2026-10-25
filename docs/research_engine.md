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
- Stale-metric gate: any metric whose latest period end is older than ~2
  years (731 days) is excluded from scoring with an explicit flag. This
  catches abandoned tags and silently incomplete retrievals (e.g. a
  truncated concept response that ends years ago) instead of letting old
  numbers drive a score. Fewer than 4 current core metrics after exclusion
  -> `INSUFFICIENT_DATA`.
- Same-period matching only: margins are computed from identical period
  end dates, never mixed periods.
- Annual-continuity check: a >550-day gap between consecutive recent
  annual facts in a flow metric is flagged as possible missing data.

## Data-integrity limitation (read before trusting any brief)
The fetch route (an HTTP reader with a per-response size cap) can return
silently incomplete concept JSON: valid syntax, facts dropped, no marker.
Observed in practice (head+tail kept, middle elided). Mitigations in the
engine: the stale-metric gate drops series whose latest fact is implausibly
old, and the continuity check flags gaps inside recent annual series.
Neither proves a response is complete: a partial response can still look
current. Treat every brief as "best available from a capped retrieval",
not a guaranteed-complete record. Facts carry citations (concept, period,
accession number) so any number can be verified against the SEC original.

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

## Candidate screening mode
    python3 scripts/research_engine.py --config private_universe.json \
        --cache-dir cache --out screen_out --screen [--min-rules 4]

- Same deterministic pipeline and gates as holdings review; the universe
  config is private, exactly like the holdings config.
- Universe entries may omit `cik` and give only `ticker`: the CIK is resolved
  from SEC's `company_tickers.json` (cached; fetched only under `--fetch`
  with the declared UA). An unresolved ticker is EXCLUDED - never guessed.
- A candidate ranks only when at least `--min-rules` of the 5 rules scored
  (default 4). Below that it is marked SCREENED_OUT with the reason; the
  brief says so. `INSUFFICIENT_DATA` candidates are excluded the same way.
- Briefs are labeled "Candidate screen brief ... Screening candidate - not a
  holding" with the same not-a-prediction wording plus "not a solicitation".
- `summary.json` gains `mode: screen`, `min_rules`, a `ranking` array
  (rank, score, band, scored_rules, flag count) and an `excluded` array
  with per-candidate reasons.
- Screening output is research groundwork for agent review; the universe
  list itself is chosen outside the engine and is not endorsed by it.
