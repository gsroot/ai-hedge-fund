"""Decision-path regressions using only synthetic prices and financial observations."""
import sys
import json
import tempfile
import unittest
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / ".agents/skills/predict/scripts"
sys.path.insert(0, str(SCRIPTS))
import analysis
import analyze_stocks
import cache
import data_fetcher
from research_ranking import build_research_shortlist, observed_prices, rank_research_rows
from ticker_utils import completed_korean_price_date

DAY = date(2026, 3, 25)
PRICES = [{"time": (DAY - timedelta(days=69-i)).isoformat(), "close": 80.0+i} for i in range(70)]
METRICS = {"company_name": "Example", "market_cap": 1.e9, "price_to_book_ratio": 1.2,
           "revenue_growth": 0.0, "return_on_equity": 0.15, "debt_to_equity": 0.0}


def analyze(strategy, bars=PRICES, metrics=METRICS):
    with patch.object(analysis, "get_financial_metrics", return_value=[metrics]), \
            patch("financial_datasets_api.get_analyst_estimates", return_value=None):
        return analysis.analyze_single_ticker_detailed(
            "AAA", DAY.isoformat(), prefetched_prices=bars, strategy=strategy, skip_news=True)


class ResearchRankingTests(unittest.TestCase):
    def test_price_only_momentum_never_fetches_financials_or_news(self):
        with patch.object(analysis, "get_financial_metrics", side_effect=AssertionError), \
                patch.object(analysis, "get_company_news", side_effect=AssertionError):
            row, reason = analysis.analyze_single_ticker_detailed(
                "AAA", DAY.isoformat(), prefetched_prices=PRICES, strategy="momentum")
        self.assertIsNone(reason)
        self.assertIsNone(row["scores"]["quality"])
        self.assertEqual(row["research_evidence"]["price_end"], DAY.isoformat())
        self.assertEqual(row["total_score"], row["scores"]["enhanced_momentum"])

    def test_stale_short_and_future_prices_do_not_supply_momentum(self):
        self.assertEqual(analyze("momentum", PRICES[-5:])[1], "insufficient_price_history")
        self.assertEqual(analyze("momentum", PRICES[:-10])[1], "prices_stale")
        invalid = [{"time": "2027-01-01", "close": 1}, {"time": DAY.isoformat(), "close": float("inf")}]
        self.assertEqual(analyze("momentum", invalid)[1], "prices_unavailable")

    def test_partial_hybrid_uses_observed_business_without_synthetic_momentum(self):
        row, reason = analyze("hybrid", PRICES[-3:])
        self.assertIsNone(reason)
        self.assertIsNone(row["scores"]["enhanced_momentum"])
        self.assertIsNone(row["scores"]["insider"])
        self.assertEqual(row["metrics"]["revenue_growth"], 0.0)
        self.assertEqual(row["research_evidence"]["fundamental_fields"]["safety"]["debt_to_equity"], 0.0)
        self.assertEqual(analyze("hybrid", metrics={"market_cap": 100000})[1], "insufficient_fundamental_coverage")
        self.assertEqual(analyze("hybrid", metrics={**METRICS, "quote_type": "ETF"})[1], "non_company_instrument")

    def test_market_cap_is_optional_and_zero_is_a_real_business_input(self):
        self.assertTrue(data_fetcher.has_usable_metrics({"free_cash_flow_yield": 0.0}))
        self.assertFalse(data_fetcher.has_usable_metrics({"free_cash_flow_yield": False}))
        poorest, _ = analyze("fundamental", metrics={"operating_margin": 0., "return_on_equity": 0.,
                                                    "current_ratio": 0., "debt_to_equity": -2.})
        weak, _ = analyze("fundamental", metrics={"operating_margin": .001, "return_on_equity": .001,
                                                  "current_ratio": .01, "debt_to_equity": .4})
        self.assertEqual(poorest["rank_inputs"]["quality"], weak["rank_inputs"]["quality"])
        self.assertLess(poorest["rank_inputs"]["safety"], weak["rank_inputs"]["safety"])

    def test_unobserved_weights_cannot_concentrate_on_a_single_good_factor(self):
        base, _ = analyze("hybrid")
        sparse = {**base, "ticker": "SPARSE", "rank_inputs": {"value": 99, "safety": 0}}
        rich = {**base, "ticker": "RICH", "rank_inputs": {key: 100 for key in base["rank_inputs"]}}
        rows = rank_research_rows([sparse, rich, base], "hybrid")
        candidate = next(r for r in rows if r["ticker"] == "SPARSE")
        self.assertAlmostEqual(candidate["observed_weight_share"], .35)
        self.assertAlmostEqual(candidate["research_weights"]["value"], .25)
        self.assertLessEqual(abs(candidate["total_score"] - 5), .35 * 5)

    def test_dated_inputs_and_completed_seoul_days(self):
        bars, reason = observed_prices([{"date": "2026-03-25T09:00:00+09:00", "close": 10, "provider": "pykrx"},
                                        {"time": "2026-03-25", "close": 10}], DAY.isoformat())
        self.assertIsNone(reason)
        self.assertEqual(len(bars), 1)
        self.assertEqual(bars[0]["providers"], ["pykrx"])
        self.assertEqual(observed_prices(PRICES + [{**PRICES[-1], "close": 99}], DAY.isoformat())[1],
                         "conflicting_daily_closes")
        self.assertEqual(completed_korean_price_date("2026-03-25", datetime(2026, 3, 25, 14, 59, tzinfo=UTC)), "2026-03-24")
        self.assertEqual(completed_korean_price_date("2026-03-25", datetime(2026, 3, 25, 15, 0, tzinfo=UTC)), "2026-03-25")

    def test_gifts_and_unsigned_shares_are_not_directional_transactions(self):
        gift = {"shares": 1000, "transaction_type": "Gift"}
        with patch.object(analysis, "get_financial_metrics", return_value=[METRICS]), \
                patch.object(analysis, "get_company_news", side_effect=TimeoutError), \
                patch.object(analysis, "get_insider_trades", return_value=[gift]):
            row, reason = analysis.analyze_single_ticker_detailed("AAA", DAY.isoformat(), PRICES)
        self.assertIsNone(reason)
        self.assertIsNone(row["scores"]["insider"])
        self.assertEqual(row["research_evidence"]["insider_status"], "no_usable_observations")
        self.assertEqual(row["research_evidence"]["keyword_news_status"], "unavailable:TimeoutError")
        trades = analysis._directional_trades([{"transaction_type": "Purchase at price 10", "ownership_type": "Indirect"}])
        self.assertEqual(trades[0]["ownership_type"], "")

    def test_market_cap_and_legacy_evidence_cannot_silently_select(self):
        quotes = {"A": {}, "B": {"marketCap": 7}, "C": {"marketCap": 9}}
        missing = []
        with patch.object(data_fetcher, "safe_get_ticker_info", side_effect=quotes.get):
            self.assertEqual(data_fetcher.sort_tickers_by_market_cap(["A", "B", "C"], top_n=3, unavailable=missing), ["C", "B"])
        self.assertEqual(missing, ["A"])
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "evidence.json"
            path.write_text(json.dumps({"factor_spec_id": "predict_factor_v1"}), encoding="utf-8")
            policy = analyze_stocks.research_factor_policy(path, "us", "sp500", DAY.isoformat())
            self.assertEqual(policy["mode"], "prior_only")
            self.assertFalse(policy["submitted_evidence"]["applied_to_ranking"])
            with patch.object(cache.config, "CACHE_ENABLED", False):
                self.assertIsNone(cache._read_cache(path))
                cache._write_cache(path, {"overwritten": True})
                self.assertIn("factor_spec_id", json.loads(path.read_text(encoding="utf-8")))

    def test_rank_depends_only_on_observed_factors_and_preserves_ties(self):
        a, _ = analyze("hybrid")
        b, _ = analyze("hybrid", metrics={**METRICS, "price_to_book_ratio": 12.0})
        rows = rank_research_rows([{**b, "ticker": "B"}, {**a, "ticker": "Z"}, a], "hybrid")
        self.assertEqual([r["ticker"] for r in rows], ["AAA", "Z", "B"])
        self.assertEqual(rows[0]["total_score"], rows[1]["total_score"])
        self.assertNotIn("insider", rows[0]["research_weights"])
        self.assertLess(rows[-1]["factor_percentiles"]["value"], rows[0]["factor_percentiles"]["value"])

    def test_shortlist_keeps_complementary_candidate_outside_rank_leaders(self):
        rows = [{"rank": i, "ticker": str(i), "metrics": {"sector": "A" if i < 12 else "B"},
                 "factor_percentiles": {"value": float(i)}} for i in range(1, 13)]
        slate = build_research_shortlist(rows)
        last = next(r for r in slate["candidates"] if r["ticker"] == "12")
        self.assertIn("sector:B", last["reasons"])
        self.assertIn("factor:value", last["reasons"])
        self.assertEqual(len(slate["candidates"]), len({r["ticker"] for r in slate["candidates"]}))

if __name__ == "__main__":
    unittest.main()
