#!/usr/bin/env python3
"""Unit tests for research_engine.py - synthetic fixtures only, no network."""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import research_engine as re_eng


def concept(points):
    return {"cik": 1, "taxonomy": "us-gaap", "tag": "X", "label": "X",
            "entityName": "Test Co", "units": {"USD": points}}


def pt(val, start, end, filed, form="10-K", fp="FY"):
    return {"start": start, "end": end, "val": val, "accn": "000-1",
            "fy": int(end[:4]), "fp": fp, "form": form, "filed": filed}


class AnnualSeriesTests(unittest.TestCase):
    def test_dedupe_by_end_keeps_latest_filed(self):
        c = concept([
            pt(100, "2024-01-01", "2024-12-31", "2025-02-01"),
            pt(105, "2024-01-01", "2024-12-31", "2025-03-01", form="10-K/A"),
        ])
        s = re_eng.annual_series(c)
        self.assertEqual(len(s), 1)
        self.assertEqual(s[0]["val"], 105)

    def test_rejects_short_and_quarterly_periods(self):
        c = concept([
            pt(50, "2024-01-01", "2024-03-31", "2024-05-01", fp="Q1"),
            pt(60, "2024-01-01", "2024-06-30", "2024-08-01", fp="Q2"),
            pt(200, "2024-01-01", "2024-12-31", "2025-02-01"),
        ])
        s = re_eng.annual_series(c)
        self.assertEqual(len(s), 1)
        self.assertEqual(s[0]["val"], 200)


class InstantSeriesTests(unittest.TestCase):
    def test_instant_facts_no_start_date(self):
        pts = [{"start": None, "end": "2024-12-31", "val": 50, "accn": "a",
                "fy": 2024, "fp": "FY", "form": "10-K", "filed": "2025-02-01"},
               {"start": None, "end": "2024-12-31", "val": 55, "accn": "b",
                "fy": 2024, "fp": "FY", "form": "10-K/A", "filed": "2025-03-01"},
               {"start": None, "end": "2024-06-30", "val": 48, "accn": "c",
                "fy": 2024, "fp": "Q2", "form": "10-Q", "filed": "2024-08-01"}]
        s = re_eng.instant_series(concept(pts))
        self.assertEqual(len(s), 2)  # FY 10-K/A dedupe + the 10-Q point
        self.assertEqual(s[-1]["val"], 55)  # latest filed wins for 2024-12-31


class CagrTests(unittest.TestCase):
    def test_known_cagr(self):
        # 100 -> 121 over exactly 2 years = 10% per year
        c = concept([
            pt(100, "2021-01-01", "2021-12-31", "2022-02-01"),
            pt(110, "2022-01-01", "2022-12-31", "2023-02-01"),
            pt(121, "2023-01-01", "2023-12-31", "2024-02-01"),
        ])
        g, s, e = re_eng.cagr(re_eng.annual_series(c))
        self.assertAlmostEqual(g, 0.10, places=2)
        self.assertEqual((s, e), ("2021-12-31", "2023-12-31"))

    def test_uncomputable_when_negative_base(self):
        c = concept([
            pt(-5, "2021-01-01", "2021-12-31", "2022-02-01"),
            pt(10, "2022-01-01", "2022-12-31", "2023-02-01"),
        ])
        g, _, _ = re_eng.cagr(re_eng.annual_series(c))
        self.assertIsNone(g)


FIXTURE_TICKER = "TEST"
FIXTURE_CIK = "0000000001"


def write_fixture(cache, cik, tax, tag, points):
    os.makedirs(cache, exist_ok=True)
    with open(os.path.join(cache, f"{cik}_{tax}_{tag}.json"), "w") as f:
        json.dump({"cik": int(cik), "taxonomy": tax, "tag": tag, "label": tag,
                   "entityName": "Test Co", "units": {"USD": points}}, f)


def healthy_fixture(cache, cik=FIXTURE_CIK):
    rev = [pt(v, f"{y}-01-01", f"{y}-12-31", f"{y+1}-02-15")
           for y, v in [(2021, 100), (2022, 112), (2023, 126), (2024, 141)]]
    opi = [pt(v, f"{y}-01-01", f"{y}-12-31", f"{y+1}-02-15")
           for y, v in [(2022, 20), (2023, 24), (2024, 28)]]
    ni = [pt(v, f"{y}-01-01", f"{y}-12-31", f"{y+1}-02-15")
          for y, v in [(2022, 15), (2023, 18), (2024, 21)]]
    ocf = [pt(v, f"{y}-01-01", f"{y}-12-31", f"{y+1}-02-15")
           for y, v in [(2020, 30), (2021, 31), (2022, 32), (2023, 33), (2024, 34)]]
    debt = [pt(50, "2024-01-01", "2024-12-31", "2025-02-15")]
    eq = [pt(200, "2024-01-01", "2024-12-31", "2025-02-15")]
    cash = [pt(40, "2024-01-01", "2024-12-31", "2025-02-15")]
    write_fixture(cache, cik, "us-gaap", "RevenueFromContractWithCustomerExcludingAssessedTax", rev)
    write_fixture(cache, cik, "us-gaap", "OperatingIncomeLoss", opi)
    write_fixture(cache, cik, "us-gaap", "NetIncomeLoss", ni)
    write_fixture(cache, cik, "us-gaap", "NetCashProvidedByUsedInOperatingActivities", ocf)
    write_fixture(cache, cik, "us-gaap", "LongTermDebt", debt)
    write_fixture(cache, cik, "us-gaap", "StockholdersEquity", eq)
    write_fixture(cache, cik, "us-gaap", "CashAndCashEquivalentsAtCarryingValue", cash)


class ScoreCompanyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cache = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def run_engine(self):
        src = re_eng.ConceptSource(self.cache, allow_fetch=False)
        return re_eng.score_company(src, FIXTURE_CIK, "Test Co",
                                    today=__import__("datetime").date(2025, 3, 1))

    def test_healthy_company_scores_strong(self):
        healthy_fixture(self.cache)
        r = self.run_engine()
        self.assertEqual(r["status"], "OK")
        # CAGR 100->141 over 3y = ~12.1% (2), op margin 28/141 ~19.9% (2),
        # net margin >0 (1), D/E 0.25 (2), OCF 5/5 (2) = 9 -> strong
        self.assertEqual(r["score"], 9)
        self.assertEqual(r["band"], "strong")
        self.assertAlmostEqual(r["metrics"]["operating_margin"]["value"], 28 / 141, places=3)

    def test_tag_fallback_to_current_tag(self):
        healthy_fixture(self.cache)
        # legacy Revenues tag stops in 2018; fallback must prefer the current tag
        write_fixture(self.cache, FIXTURE_CIK, "us-gaap", "Revenues",
                      [pt(80, "2017-01-01", "2017-12-31", "2018-02-01")])
        r = self.run_engine()
        cit = r["metrics"]["revenue_cagr"]["citation"]
        self.assertEqual(cit["tag"], "RevenueFromContractWithCustomerExcludingAssessedTax")
        self.assertEqual(cit["end"], "2024-12-31")

    def test_foreign_filer_ifrs_tags(self):
        cache = self.cache
        rev = [pt(v, f"{y}-01-01", f"{y}-12-31", f"{y+1}-03-01")
               for y, v in [(2021, 200), (2022, 220), (2023, 250), (2024, 280)]]
        pl = [pt(v, f"{y}-01-01", f"{y}-12-31", f"{y+1}-03-01")
              for y, v in [(2022, 40), (2023, 50), (2024, 60)]]
        cfo = [pt(v, f"{y}-01-01", f"{y}-12-31", f"{y+1}-03-01")
               for y, v in [(2020, 70), (2021, 71), (2022, 72), (2023, 73), (2024, 74)]]
        debt = [pt(10, "2024-01-01", "2024-12-31", "2025-03-01")]
        eq = [pt(300, "2024-01-01", "2024-12-31", "2025-03-01")]
        cash = [pt(50, "2024-01-01", "2024-12-31", "2025-03-01")]
        write_fixture(cache, FIXTURE_CIK, "ifrs-full", "Revenue", rev)
        write_fixture(cache, FIXTURE_CIK, "ifrs-full", "ProfitLoss", pl)
        write_fixture(cache, FIXTURE_CIK, "ifrs-full", "CashFlowsFromUsedInOperatingActivities", cfo)
        write_fixture(cache, FIXTURE_CIK, "ifrs-full", "NoncurrentBorrowings", debt)
        write_fixture(cache, FIXTURE_CIK, "ifrs-full", "Equity", eq)
        write_fixture(cache, FIXTURE_CIK, "ifrs-full", "CashAndCashEquivalents", cash)
        r = self.run_engine()
        self.assertEqual(r["status"], "OK")
        self.assertIsNotNone(r["score"])

    def test_insufficient_data_not_scored(self):
        # only 2 core metrics present
        write_fixture(self.cache, FIXTURE_CIK, "us-gaap",
                      "RevenueFromContractWithCustomerExcludingAssessedTax",
                      [pt(100, "2024-01-01", "2024-12-31", "2025-02-01")])
        write_fixture(self.cache, FIXTURE_CIK, "us-gaap", "NetIncomeLoss",
                      [pt(10, "2024-01-01", "2024-12-31", "2025-02-01")])
        r = self.run_engine()
        self.assertEqual(r["status"], "INSUFFICIENT_DATA")
        self.assertIsNone(r["score"])

    def test_stale_filings_flagged_not_current(self):
        healthy_fixture(self.cache)
        src = re_eng.ConceptSource(self.cache, allow_fetch=False)
        import datetime as dtmod
        r = re_eng.score_company(src, FIXTURE_CIK, "Test Co", today=dtmod.date(2027, 1, 1))
        self.assertEqual(r["status"], "NOT_CURRENT")
        self.assertIsNone(r["score"])

    def test_stale_metric_excluded_from_scoring(self):
        healthy_fixture(self.cache)
        # debt tag abandoned a decade ago (real pattern: filer stops using a tag)
        write_fixture(self.cache, FIXTURE_CIK, "us-gaap", "LongTermDebt",
                      [pt(50, "2014-01-01", "2014-12-31", "2015-02-15")])
        r = self.run_engine()
        self.assertNotIn("debt_to_equity", r["metrics"])
        self.assertTrue(any("stale metric long_term_debt" in f for f in r["flags"]))
        # score is 7 from the remaining four rules, not 9 with stale leverage
        self.assertEqual(r["score"], 7)

    def test_annual_continuity_gap_flagged(self):
        healthy_fixture(self.cache)
        # a silently elided retrieval: FY2022 revenue fact missing from cache
        rev = [pt(v, f"{y}-01-01", f"{y}-12-31", f"{y+1}-02-15")
               for y, v in [(2021, 100), (2023, 126), (2024, 141)]]
        write_fixture(self.cache, FIXTURE_CIK, "us-gaap",
                      "RevenueFromContractWithCustomerExcludingAssessedTax", rev)
        r = self.run_engine()
        self.assertTrue(any("possible missing annual facts in revenue" in f
                            for f in r["flags"]))

    def test_emptied_facts_array_is_suspect_not_missing(self):
        healthy_fixture(self.cache)
        # retrieval artifact: facts array replaced by an empty object
        write_fixture(self.cache, FIXTURE_CIK, "us-gaap", "LongTermDebt", {})
        r = self.run_engine()
        self.assertTrue(any("suspect retrieval" in f for f in r["flags"]))
        self.assertNotIn("debt_to_equity", r["metrics"])
        # debt wording must NOT claim "no standard debt concept filed"
        self.assertFalse(any("NOT evidence of zero debt" in f for f in r["flags"]))

    def test_missing_metric_lists_all_attempts(self):
        healthy_fixture(self.cache)
        os.remove(os.path.join(self.cache, FIXTURE_CIK + "_us-gaap_LongTermDebt.json"))
        r = self.run_engine()
        debt_flags = [f for f in r["flags"] if f.startswith("missing metric long_term_debt")]
        self.assertEqual(len(debt_flags), 1)
        self.assertIn("us-gaap/LongTermDebt", debt_flags[0])
        self.assertIn("ifrs-full/NoncurrentBorrowings", debt_flags[0])
        self.assertIn("NOT evidence of zero debt", debt_flags[0])


    def _stmts_dir(self, files):
        d = tempfile.TemporaryDirectory()
        for name, pts in files.items():
            with open(os.path.join(d.name, name + ".json"), "w") as f:
                json.dump(pts, f)
        self.addCleanup(d.cleanup)
        return d.name

    def _run_with_stmts(self, sdir):
        src = re_eng.ConceptSource(self.cache, allow_fetch=False)
        stmts = re_eng.StatementSource(sdir)
        return re_eng.score_company(src, FIXTURE_CIK, "Test Co",
                                    today=__import__("datetime").date(2025, 3, 1),
                                    statements=stmts)

    @staticmethod
    def _spt(val, start, end, filed="2025-02-20"):
        p = {"end": end, "val": val, "form": "10-K", "accn": "000-1",
             "filed": filed, "statement_url": "https://www.sec.gov/x/R5.htm",
             "extractor": "agent-rfile-v1"}
        if start:
            p["start"] = start
        return p

    def test_statements_fill_when_concept_missing(self):
        healthy_fixture(self.cache)
        os.remove(os.path.join(self.cache, FIXTURE_CIK + "_us-gaap_NetIncomeLoss.json"))
        sdir = self._stmts_dir({
            FIXTURE_CIK + "_net_income": [self._spt(20, "2024-01-01", "2024-12-31")],
        })
        r = self._run_with_stmts(sdir)
        self.assertIn("net_margin", r["metrics"])
        self.assertTrue(any("filled from original filing statement" in f and "not automatic coverage" in f
                            for f in r["flags"]))
        cit = r["metrics"]["net_margin"]
        self.assertIsNotNone(cit.get("value"))

    def test_statements_not_used_when_concept_healthy(self):
        healthy_fixture(self.cache)
        # statement tier carries a DIFFERENT (bogus) NI value; concept must win
        sdir = self._stmts_dir({
            FIXTURE_CIK + "_net_income": [self._spt(999999, "2024-01-01", "2024-12-31")],
        })
        r = self._run_with_stmts(sdir)
        # healthy fixture NI is 21; net margin must use the concept value
        self.assertAlmostEqual(r["metrics"]["net_margin"]["value"], 21 / 141, places=3)
        self.assertFalse(any("filled from original filing statement" in f for f in r["flags"]))

    def test_statements_fill_after_stale_exclusion(self):
        healthy_fixture(self.cache)
        write_fixture(self.cache, FIXTURE_CIK, "us-gaap", "NetIncomeLoss",
                      [pt(5, "2014-01-01", "2014-12-31", "2015-02-15")])
        sdir = self._stmts_dir({
            FIXTURE_CIK + "_net_income": [self._spt(22, "2024-01-01", "2024-12-31")],
        })
        r = self._run_with_stmts(sdir)
        self.assertIn("net_margin", r["metrics"])
        self.assertAlmostEqual(r["metrics"]["net_margin"]["value"], 22 / 141, places=3)
        self.assertTrue(any("after the concept-feed" in f and "excluded as stale" in f
                            for f in r["flags"]))
        self.assertFalse(any(f.startswith("stale metric net_income") for f in r["flags"]))

    def test_statements_stale_fill_also_rejected(self):
        healthy_fixture(self.cache)
        os.remove(os.path.join(self.cache, FIXTURE_CIK + "_us-gaap_NetIncomeLoss.json"))
        sdir = self._stmts_dir({
            FIXTURE_CIK + "_net_income": [self._spt(22, "2010-01-01", "2010-12-31", filed="2011-02-01")],
        })
        r = self._run_with_stmts(sdir)
        self.assertNotIn("net_margin", r["metrics"])


    def _mk(self, name, score, band, metric_vals, status="OK"):
        metrics = {k: {"value": v, "end": "2024-12-31"} for k, v in metric_vals.items()}
        return {"ticker": name, "name": name, "cik": "0000000001", "status": status,
                "score": score, "band": band, "metrics": metrics, "flags": [],
                "as_of": "2025-03-01", "latest_filing_date": "2025-02-15"}

    def test_screen_ranks_and_excludes_thin_data(self):
        full = {k: 1.0 for k in re_eng.RULE_METRICS}
        thin = {"revenue_cagr": 0.1, "net_margin": 0.2, "ocf_positive_years": 5}
        results = [
            self._mk("MidCo", 7, "adequate", full),
            self._mk("TopCo", 9, "strong", full),
            self._mk("ThinCo", 3, "weak", thin),
            self._mk("NoData", None, None, {}, status="INSUFFICIENT_DATA"),
        ]
        ranked, excluded = re_eng.apply_screen(results, min_rules=4)
        self.assertEqual([r["name"] for r in ranked], ["TopCo", "MidCo"])
        self.assertEqual(ranked[0]["scored_rules"], 5)
        by_name = {e["name"]: e for e in excluded}
        self.assertIn("ThinCo", by_name)
        self.assertIn("only 3 of 5 rules", by_name["ThinCo"]["reason"])
        self.assertEqual(by_name["NoData"]["status"], "INSUFFICIENT_DATA")

    def test_screen_exclusion_rendered_in_candidate_brief(self):
        thin = {"revenue_cagr": 0.1}
        r = self._mk("ThinCo", 3, "weak", thin)
        re_eng.apply_screen([r], min_rules=4)
        md = re_eng.render_md(r, candidate=True)
        self.assertIn("Candidate screen brief", md)
        self.assertIn("Screening candidate - not a holding", md)
        self.assertIn("Excluded from ranking", md)
        self.assertIn("not a solicitation", md)

    def test_resolve_ticker_from_cached_map(self):
        with open(os.path.join(self.cache, "_company_tickers.json"), "w") as f:
            json.dump({"0": {"cik_str": 12345, "ticker": "ABC", "title": "Abc Corp"},
                       "1": {"cik_str": 99999, "ticker": "XYZ", "title": "Xyz Inc"}}, f)
        src = re_eng.ConceptSource(self.cache, allow_fetch=False)
        self.assertEqual(re_eng.resolve_ticker(src, "abc"), "0000012345")
        self.assertIsNone(re_eng.resolve_ticker(src, "QQQ"))

    def test_resolve_ticker_no_map_no_fetch_returns_none(self):
        src = re_eng.ConceptSource(self.cache, allow_fetch=False)
        self.assertIsNone(re_eng.resolve_ticker(src, "ABC"))


    def test_screen_equal_score_more_coverage_ranks_higher(self):
        # 7/9 (all 5 rules scored) vs 7/7 (leverage skipped): same raw score,
        # the fully-evidenced one must rank first - percentages would tie them.
        full = {"revenue_cagr": 0.10, "operating_margin": 0.20, "net_margin": 0.05,
                "debt_to_equity": 1.0, "ocf_positive_years": 5}  # 2+2+1+1+... adjust: raw 7
        nolev = {"revenue_cagr": 0.10, "operating_margin": 0.20, "net_margin": 0.05,
                 "ocf_positive_years": 5}  # leverage skipped; raw also 7 (2+2+1+2)
        full_r = self._mk("FullCo", 7, "adequate", full)
        skip_r = self._mk("SkipCo", 7, "adequate", nolev)
        ranked, _ = re_eng.apply_screen([skip_r, full_r], min_rules=4)
        self.assertEqual([r["name"] for r in ranked], ["FullCo", "SkipCo"])
        self.assertEqual(ranked[0]["available_points"], 9)
        self.assertEqual(ranked[1]["available_points"], 7)
        self.assertEqual(ranked[1]["skipped_rules"], ["debt_to_equity"])

    def test_screen_never_ranks_by_percentage_of_available(self):
        # 8/9 (89%) must outrank 7/7 (100%): raw score is primary, so missing
        # evidence is never rewarded by normalization.
        full = {k: 1.0 for k in re_eng.RULE_METRICS}
        nolev = {"revenue_cagr": 0.1, "operating_margin": 0.2, "net_margin": 0.1,
                 "ocf_positive_years": 5}
        eight = self._mk("EightCo", 8, "strong", full)
        seven = self._mk("SevenCo", 7, "adequate", nolev)
        ranked, _ = re_eng.apply_screen([seven, eight], min_rules=4)
        self.assertEqual([r["name"] for r in ranked], ["EightCo", "SevenCo"])

    def test_screen_coverage_line_in_ranked_brief(self):
        nolev = {"revenue_cagr": 0.1, "operating_margin": 0.2, "net_margin": 0.1,
                 "ocf_positive_years": 5}
        r = self._mk("SkipCo", 7, "adequate", nolev)
        re_eng.apply_screen([r], min_rules=4)
        md = re_eng.render_md(r, candidate=True)
        self.assertIn("Coverage: 4 of 5 rules scored (7 of 9 points available)", md)
        self.assertIn("skipped: leverage", md)
        self.assertIn("not treated as pass or fail", md)

    def test_mixed_period_margin_refused(self):
        healthy_fixture(self.cache)
        # operating income only for a period with no matching revenue end date
        write_fixture(self.cache, FIXTURE_CIK, "us-gaap", "OperatingIncomeLoss",
                      [pt(99, "2023-06-01", "2024-05-31", "2024-08-01")])
        r = self.run_engine()
        self.assertNotIn("operating_margin", r["metrics"])
        self.assertTrue(any("same-period" in f for f in r["flags"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
