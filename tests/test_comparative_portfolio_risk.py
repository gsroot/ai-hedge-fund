import math
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import pandas as pd


SCRIPTS = Path(__file__).resolve().parents[1] / ".agents/skills/portfolio-report/scripts"
sys.path.insert(0, str(SCRIPTS))
import build_risk_snapshot as builder
from portfolio_risk import compare_portfolio_risk


def rows(days, closes):
    return [{"date": str(day.date()), "close": close} for day, close in zip(days, closes)]


class RiskComparisonTests(unittest.TestCase):
    def setUp(self):
        self.days = pd.bdate_range(end="2026-11-06", periods=5)
        self.prices = {
            "A": rows(self.days, [100, 80, 100, 110, 99]),
            "SPY": rows(self.days, [100, 100, 100, 100, 100]),
            "USDKRW=X": rows(self.days, [10, 20, 10, 10, 10]),
        }

    def snapshot(self, tickers=("A",), **kwargs):
        with patch.object(builder, "get_prices", side_effect=lambda t, s, e: self.prices[t]):
            return builder.build_risk_snapshot(tickers, "2026-11-06", min_observations=2, **kwargs)

    def test_common_date_buy_and_hold_drawdown_and_first_interval(self):
        comparisons = compare_portfolio_risk(
            self.snapshot(), {"half": {"A": .5}, "cash": {}, "whole": {"A": 1}},
            base_currency="USD", quote_currencies={"A": "USD"}, cash_currency="USD")
        self.assertEqual(comparisons["status"], "available")
        self.assertEqual(comparisons["observations"], 4)
        plans = comparisons["portfolios"]
        self.assertAlmostEqual(plans["half"]["max_drawdown"], -.1)
        self.assertAlmostEqual(plans["half"]["worst_interval_return"], -.1)
        self.assertAlmostEqual(plans["whole"]["max_drawdown"], -.2)
        self.assertEqual(plans["cash"]["max_drawdown"], 0)

    def test_fx_allows_asset_and_cash_with_direct_rate_only(self):
        snapshot = self.snapshot(fx_pairs=["USD/KRW"])
        plans = {"hedgeless": {"A": 1}, "foreign_cash": {}, "base_cash": {}}
        result = compare_portfolio_risk(snapshot, plans, base_currency="KRW", quote_currencies={"A": "USD"},
                                        cash_currency={"foreign_cash": "USD", "base_cash": "KRW"})
        self.assertEqual(result["status"], "available")
        self.assertAlmostEqual(result["portfolios"]["foreign_cash"]["max_drawdown"], -.5)
        self.assertAlmostEqual(result["portfolios"]["hedgeless"]["max_drawdown"], 99/160-1)
        self.assertEqual(result["portfolios"]["base_cash"]["max_drawdown"], 0)
        missing = compare_portfolio_risk(self.snapshot(), {"base": {"A": 1}, "foreign_cash": {}},
                                         base_currency="USD", quote_currencies={"A": "USD"}, cash_currency="KRW")
        self.assertEqual(missing["status"], "partial")
        self.assertEqual(missing["portfolios"]["base"]["status"], "available")
        self.assertIn("missing_fx", missing["portfolios"]["foreign_cash"]["reason"])

    def test_stale_legacy_and_no_common_calendar_are_explicit(self):
        self.prices["STALE"] = rows(pd.bdate_range(end="2026-10-01", periods=5), [1, 2, 3, 4, 5])
        snapshot = self.snapshot(("A", "STALE"))
        self.assertNotIn("STALE", snapshot["annualized_volatility"])
        self.assertNotIn("STALE", snapshot["correlation"])
        self.assertEqual(snapshot["price_history"]["STALE"]["freshness"], "stale")
        result = compare_portfolio_risk(snapshot, {"fresh": {"A": 1}, "stale": {"STALE": 1}},
                                        base_currency="USD", quote_currencies={"A": "USD", "STALE": "USD"})
        self.assertEqual(result["status"], "partial")
        self.assertIn("stale", result["portfolios"]["stale"]["reason"])
        old = compare_portfolio_risk({}, {"fresh": {"A": 1}}, base_currency="USD", quote_currencies={"A": "USD"})
        self.assertEqual(old["status"], "unavailable")
        self.assertNotIn("max_drawdown", old["portfolios"]["fresh"])

    def test_incompatible_calendars_keep_separate_windows_without_comparison(self):
        self.prices["B"] = rows(pd.date_range("2026-10-27", "2026-11-05", freq="3D"), [90, 100, 95, 92])
        result = compare_portfolio_risk(self.snapshot(("A", "B")), {"A": {"A": 1}, "B": {"B": 1}},
                                        base_currency="USD", quote_currencies={"A": "USD", "B": "USD"})
        self.assertEqual(result["status"], "partial")
        self.assertFalse(result["shared_window"])
        self.assertEqual(result["portfolios"]["B"]["observations"], 3)
        self.assertEqual(result["portfolios"]["A"]["observations"], 4)

    def test_no_market_leg_can_use_actual_benchmark_calendar_for_cash(self):
        result = compare_portfolio_risk(self.snapshot(), {"cash": {}},
                                        base_currency="USD", quote_currencies={}, cash_currency="USD")
        self.assertEqual(result["status"], "available")
        self.assertEqual(result["portfolios"]["cash"]["max_drawdown"], 0)

    def test_future_or_malformed_history_disables_only_affected_plan(self):
        snapshot = self.snapshot()
        snapshot["price_history"]["A"]["relative_closes"]["2026-11-12"] = 1
        result = compare_portfolio_risk(snapshot, {"A": {"A": 1}, "cash": {}},
                                        base_currency="USD", quote_currencies={"A": "USD"}, cash_currency="USD")
        self.assertEqual(result["status"], "partial")
        self.assertIn("outside_lookback", result["portfolios"]["A"]["reason"])
        self.assertEqual(result["portfolios"]["cash"]["status"], "available")

    def test_market_regime_requires_sufficiently_continuous_recent_prices(self):
        days = pd.bdate_range(end="2026-11-06", periods=250)
        self.prices["SPY"] = rows(days.delete(slice(120, 140)), range(1, 231))
        snap = self.snapshot()
        self.assertEqual(snap["benchmark_price_status"], "sparse_price_history")
        self.assertEqual(snap["market_regime"]["data_quality"], "insufficient")
        self.assertEqual(snap["market_regime"]["cash_weight_interpretation"], "legacy_insufficient_data_policy_prior")

    def test_unrelated_calendar_keeps_single_asset_vol_and_pairwise_intervals(self):
        self.prices["B"] = rows(self.days, [110, 95, 94, 97, 90])
        self.prices["IRRELEVANT"] = rows(pd.date_range(end="2026-11-06", periods=10), list(range(1, 11)))
        dates = pd.bdate_range(end="2026-11-06", periods=8)
        self.prices["A"] = rows(dates, [20, 25, 26, 23, 24, 25, 25, 28])
        alone = self.snapshot(("A", "B"))
        with_other = self.snapshot(("A", "B", "IRRELEVANT"))
        self.assertAlmostEqual(alone["annualized_volatility"]["A"], with_other["annualized_volatility"]["A"])
        self.assertAlmostEqual(alone["correlation"]["A"]["B"], with_other["correlation"]["A"]["B"])
        self.assertEqual(with_other["pairwise_observations"]["A"]["B"], 4)

    def test_benchmark_failure_keeps_price_risk_and_shortlist_routes(self):
        del self.prices["SPY"]
        snap = self.snapshot()
        self.assertTrue(math.isfinite(snap["annualized_volatility"]["A"]))
        self.assertEqual(snap["market_regime"]["data_quality"], "insufficient")
        self.assertIn("provider_error", snap["benchmark_price_status"])
        payload = {"rankings": [{"ticker": t} for t in ["A", "B"]],
                   "research_shortlist": {"candidates": [{"ticker": "B"}]}}
        self.assertEqual(builder.risk_tickers(payload, None, "SPY"), ["B", "SPY"])
        self.assertEqual(builder.risk_tickers(payload, 1, "SPY"), ["A", "SPY"])


if __name__ == "__main__":
    unittest.main()
