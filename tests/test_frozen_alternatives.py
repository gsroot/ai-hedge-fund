"""Forward evaluation of alternatives frozen before any realized returns exist."""
from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / ".agents/skills/portfolio-report/scripts"))
from evaluate_decision import evaluate


class AlternativeEvaluationTests(unittest.TestCase):
    def setUp(self):
        fixture = json.loads((ROOT / "tests/fixtures/portfolio_decision.json").read_text(encoding="utf-8"))
        decision = fixture["decision"]
        decision["schema_version"] = "portfolio_decision_v2"
        decision["cash"]["annual_rate"] = 0
        self.data = fixture["prices"]
        self.as_of = self.data["as_of"]
        self.result = {
            "decision": decision, "decision_id": "test-alternatives", "status": "ready",
            "weights": {"AAA": .15, "MARKET": .6}, "cash_weight": .25,
            "portfolio_comparison": {"portfolios": {
                "selected": self.row({"AAA": .15, "MARKET": .6, "CASH": .25}, .00015),
                "current": self.row({"MARKET": .6, "CASH": .4}, 0),
                "all_cash": self.row({"CASH": 1}, .0006),
                "benchmark_reserve": self.row({"MARKET": .8, "CASH": .2}, .0002),
            }},
        }

    @staticmethod
    def row(weights, cost):
        return {"status": "feasible", "weights": weights,
                "transition": {"status": "estimated", "estimated_cost_weight": cost}}

    def test_transition_and_fresh_capital_have_separate_cost_bases(self):
        result = evaluate(self.result, self.data, self.as_of)
        observed = result["alternative_outcomes"]
        self.assertAlmostEqual(observed["selected"]["fresh_capital_return"], result["portfolio_return"])
        self.assertAlmostEqual(observed["current"]["from_holdings_return"], .6 * .30)
        self.assertAlmostEqual(observed["selected"]["from_holdings_return"],
                               (1 - .00015) * (.15 * 1.2 + .6 * 1.3 + .25) - 1)
        self.assertAlmostEqual(observed["all_cash"]["from_holdings_return"], -.0006)
        self.assertEqual(observed["selected"]["selected_minus_alternative_fresh"], 0)
        self.assertAlmostEqual(observed["current"]["selected_minus_alternative_from_holdings"],
                               observed["selected"]["from_holdings_return"] - .18)

    def test_missing_alternative_price_preserves_selected_and_marks_incomplete(self):
        old = {**copy.deepcopy(self.result["decision"]["assets"][0]), "ticker": "OLD", "weight": 0}
        self.result["decision"]["assets"].append(old)
        self.result["portfolio_comparison"]["portfolios"]["current"] = self.row({"OLD": 1}, 0)
        result = evaluate(self.result, self.data, self.as_of)
        self.assertEqual(result["status"], "complete")
        current = result["alternative_outcomes"]["current"]
        self.assertEqual(current["status"], "incomplete")
        self.assertNotIn("fresh_capital_return", current)
        self.assertIn("OLD", str(current["issues"]))

    def test_missing_selected_does_not_erase_observed_baselines(self):
        del self.data["series"]["AAA"]
        result = evaluate(self.result, self.data, self.as_of)
        self.assertEqual(result["status"], "incomplete")
        self.assertEqual(result["alternative_outcomes"]["benchmark_reserve"]["status"], "complete")
        self.assertIsNone(result["alternative_outcomes"]["all_cash"]["selected_minus_alternative_fresh"])

    def test_invalid_basis_or_unobservable_close_affects_only_the_owner(self):
        for override in ({"price_basis": "unadjusted"}, {"retrieved_at": "2026-09-10T00:00:00Z"}):
            with self.subTest(override=override):
                self.data["series"]["OLD"] = {**self.data["series"]["AAA"], **override}
                self.result["decision"]["assets"].append({**self.result["decision"]["assets"][0], "ticker": "OLD"})
                self.result["portfolio_comparison"]["portfolios"]["current"] = self.row({"OLD": 1}, 0)
                outcomes = evaluate(self.result, self.data, self.as_of)["alternative_outcomes"]
                self.assertEqual(outcomes["selected"]["status"], "complete")
                self.assertEqual(outcomes["current"]["status"], "incomplete")
                self.result["decision"]["assets"].pop()

    def test_unknown_holdings_and_infeasible_scenarios_stay_labelled(self):
        plans = self.result["portfolio_comparison"]["portfolios"]
        plans["current"].update(weights=None, status="unavailable")
        plans["selected"]["transition"] = {"status": "unavailable", "reason": "partial holdings"}
        plans["benchmark_reserve"]["status"] = "infeasible"
        outcomes = evaluate(self.result, self.data, self.as_of)["alternative_outcomes"]
        self.assertIsNone(outcomes["selected"]["from_holdings_return"])
        self.assertEqual(outcomes["current"]["status"], "unavailable")
        self.assertEqual(outcomes["benchmark_reserve"]["formation_status"], "infeasible")

    def test_not_due_keeps_future_prices_out_of_the_result(self):
        result = evaluate(self.result, self.data, "2026-09-10T00:00:00Z")
        self.assertEqual(result["status"], "not_due")
        self.assertNotIn("alternative_outcomes", result)

    def test_session_label_cannot_select_unrelated_historical_prices(self):
        self.data["calendar"]["sessions"][0]["date"] = "2001-01-01"
        for series in self.data["series"].values():
            series["bars"][0].update(date="2001-01-01", open=1)
        with self.assertRaisesRegex(ValueError, "session date"):
            evaluate(self.result, self.data, self.as_of)

    def test_local_session_day_can_differ_from_utc(self):
        cal = self.data["calendar"]
        cal.update(id="XTEST", timezone="Asia/Seoul")
        cal["sessions"][0].update(open_at="2026-09-08T23:00:00Z", close_at="2026-09-09T06:00:00Z")
        cal["sessions"][1].update(open_at="2027-03-08T23:00:00Z", close_at="2027-03-09T06:00:00Z")
        self.result["decision"]["created_at"] = "2026-09-08T21:00:00Z"
        for series in self.data["series"].values():
            series["calendar"] = "XTEST"
        for asset in self.result["decision"]["assets"]:
            asset["calendar"] = "XTEST"
        self.assertEqual(evaluate(self.result, self.data, self.as_of)["status"], "complete")
