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
