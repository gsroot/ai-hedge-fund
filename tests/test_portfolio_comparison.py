import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from openpyxl import load_workbook

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / ".agents/skills/portfolio-report"
sys.path.insert(0, str(SKILL / "scripts"))
from decision_report import write_reports
from portfolio_decision import load_snapshot, save_snapshot, validate_decision


def inputs():
    data = json.loads((ROOT / "tests/fixtures/portfolio_decision.json").read_text(encoding="utf-8"))
    data["decision"] = json.loads((SKILL / "references/decision_example.json").read_text(encoding="utf-8"))
    return data


def assess(data, **kwargs):
    return validate_decision(data["decision"], data["predict"], data["analyses"]["analyses"],
                             data["risk"], ["buffett", "lynch", "fisher"], **kwargs)


def with_holdings(data, weights):
    data["decision"]["user_context"]["holdings"] = weights
    if weights.get("CASH", 0) > 0:
        data["decision"]["user_context"]["current_cash_currency"] = data["decision"]["cash"]["currency"]
    if abs(sum(weights.values()) - 1) < 1e-8:
        data["decision"]["comparison"]["reviews"]["current"] = {"tradeoff": "account vs proposal", "switch_condition": "retain assets if fees rise"}


class PortfolioComparisonTests(unittest.TestCase):
    def test_rejects_research_collected_later_on_the_same_day(self):
        for name, marker in (("predict", {"research_shortlist": {"candidates": []}}),
                             ("risk", {"schema_version": "portfolio_risk_v2"})):
            for observed in (None, "2026-09-08T20:01:00Z"):
                with self.subTest(name=name, observed=observed):
                    data = inputs()
                    data[name].update(marker)
                    if observed:
                        data[name]["available_at"] = observed
                    with self.assertRaisesRegex(ValueError, "available_at"):
                        assess(data)

    def test_common_assumptions_turnover_cost_and_size_counterfactual(self):
        data = inputs()
        with_holdings(data, {"AAA": .1, "MARKET": .35, "CASH": .55})
        data["decision"]["assets"][0]["quote"]["currency"] = "EUR"
        comparison = assess(data)["portfolio_comparison"]
        rows = comparison["portfolios"]
        self.assertEqual(rows["half_active_tilt"]["weights"], {"AAA": .075, "MARKET": .675, "CASH": .25})
        self.assertEqual(rows["benchmark_reserve"]["weights"], {"MARKET": .8, "CASH": .2})
        self.assertEqual(rows["current"]["transition"]["estimated_cost_weight"], 0)
        transition = rows["selected"]["transition"]
        self.assertAlmostEqual(transition["one_way_turnover"], .3)
        self.assertAlmostEqual(transition["estimated_cost_weight"], (.3 * 10 + .05 * 5) / 10000)
        base = rows["selected"]["scenarios"]["base"]
        self.assertAlmostEqual(base["gross_return"], .047)
        self.assertAlmostEqual(base["after_transition_return"], (1 - .000325) * 1.047 - 1)
        self.assertAlmostEqual(rows["all_cash"]["scenarios"]["downside"]["gross_return"], .02)
        self.assertEqual(comparison["historical_risk"]["status"], "unavailable")

    def test_partial_holdings_do_not_manufacture_cash_actions_or_costs(self):
        data = inputs()
        with_holdings(data, {"AAA": .07})
        result = assess(data)
        rows = result["portfolio_comparison"]["portfolios"]
        self.assertIsNone(rows["current"]["weights"])
        self.assertEqual(rows["selected"]["transition"]["status"], "unavailable")
        self.assertIsNone(rows["selected"]["scenarios"]["base"]["after_transition_return"])
        self.assertEqual(result["actions"]["AAA"]["action"], "target_only")

    def test_unknown_or_different_existing_cash_denomination_is_not_an_unchanged_basket(self):
        for currency in (None, "KRW"):
            with self.subTest(currency=currency):
                data = inputs()
                with_holdings(data, {"CASH": 1})
                data["decision"]["user_context"]["current_cash_currency"] = currency
                result = assess(data)
                rows = result["portfolio_comparison"]["portfolios"]
                self.assertIsNone(rows["current"]["weights"])
                self.assertEqual(rows["all_cash"]["transition"]["status"], "unavailable")
                self.assertEqual(result["actions"]["AAA"]["action"], "target_only")

    def test_monetary_reserve_is_available_after_fees_for_each_plan(self):
        data = inputs()
        doc = data["decision"]
        doc["user_context"].update(required_amount=20000, portfolio_value=100000, spending_fx_to_base=1,
                                   spending_fx_basis="same currency", liquidity_basis="user_confirmed")
        doc["cash"]["weight"] = .20
        doc["assets"][1]["weight"] = .65
        result = assess(data)
        self.assertEqual(result["status"], "blocked_input")  # tight reserve, holdings unknown
        with_holdings(data, {"CASH": 1})
        result = assess(data)
        rows = result["portfolio_comparison"]["portfolios"]
        self.assertEqual(result["status"], "infeasible")
        for name in ("selected", "benchmark_reserve"):
            self.assertAlmostEqual(rows[name]["spending_reserve"]["available_base_amount_after_cost"], 19984)
            self.assertEqual(rows[name]["status"], "infeasible")
        self.assertEqual(rows["all_cash"]["status"], "feasible")
        doc["cash"]["weight"] = .201
        doc["assets"][1]["weight"] = .649
        self.assertEqual(assess(data)["portfolio_comparison"]["portfolios"]["selected"]["status"], "feasible")

    def test_scenario_loss_limit_and_missing_are_not_zero(self):
        data = inputs()
        data["decision"]["constraints"]["max_downside_scenario_loss"] = .10
        failed = assess(data)
        self.assertEqual(failed["status"], "infeasible")
        self.assertEqual(failed["weights"], {})
        self.assertEqual(failed["portfolio_comparison"]["portfolios"]["all_cash"]["status"], "feasible")
        del data["decision"]["comparison"]["scenarios"]["downside"]["returns"]["AAA"]
        result = assess(data)
        self.assertEqual(result["status"], "blocked_input")
        outcome = result["portfolio_comparison"]["portfolios"]["selected"]["scenarios"]["downside"]
        self.assertEqual(outcome, {"status": "unavailable", "missing": ["AAA"]})
        del data["decision"]["constraints"]["max_downside_scenario_loss"]
        self.assertEqual(assess(data)["weights"]["AAA"], .15)

    def test_zero_weight_proxy_metadata_and_alternative_constraints(self):
        data = inputs()
        decision = data["decision"]
        decision["constraints"]["asset_caps"] = {"MARKET": .65}
        rows = assess(data)["portfolio_comparison"]["portfolios"]
        self.assertEqual(rows["selected"]["status"], "feasible")
        self.assertEqual(rows["benchmark_reserve"]["status"], "infeasible")
        self.assertEqual(rows["half_active_tilt"]["status"], "infeasible")
        decision["assets"][1]["weight"] = 0
        decision["cash"]["weight"] = .85
        del decision["assets"][1]["etf"]
        rows = assess(data)["portfolio_comparison"]["portfolios"]
        self.assertEqual(rows["benchmark_reserve"]["status"], "unavailable")
        self.assertIn("exposure input missing", rows["benchmark_reserve"]["input_issues"][0])

    def test_failed_sold_position_quote_and_ticker_collision(self):
        data = inputs()
        old = copy.deepcopy(data["decision"]["assets"][0])
        old.update(ticker="OLD", weight=0)
        src = dict(data["decision"]["sources"][0], id="failed", status="timeout")
        old["quote"].update(source_id="failed", value=None)
        data["decision"]["assets"].append(old)
        data["decision"]["sources"].append(src)
        with_holdings(data, {"CASH": .9, "OLD": .1})
        self.assertEqual(assess(data)["status"], "blocked_input")
        old["quote"]["source_id"] = "prices"
        with self.assertRaisesRegex(ValueError, "price"):
            assess(data)
        old["ticker"] = "CASH"
        with self.assertRaisesRegex(ValueError, "reserved"):
            assess(data)

    def test_sale_of_existing_leveraged_fund_does_not_require_new_buy_limit(self):
        data = inputs()
        old = copy.deepcopy(data["decision"]["assets"][1])
        old.update(ticker="OLD_ETF", weight=0)
        old["etf"].update(diversified=False, leverage=2)
        data["decision"]["assets"].append(old)
        with_holdings(data, {"OLD_ETF": 1})
        result = assess(data)
        self.assertEqual(result["portfolio_comparison"]["portfolios"]["current"]["status"], "unavailable")
        self.assertEqual(result["actions"]["OLD_ETF"]["action"], "exit")

    def test_final_review_mandatory_preview_unsavable_and_formats_match(self):
        data = inputs()
        del data["decision"]["comparison"]["reviews"]["all_cash"]
        with self.assertRaisesRegex(ValueError, "reviews"):
            assess(data)
        result = assess(data, preview=True)
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, "preview"):
                save_snapshot(result, tmp)
            result = assess(inputs())
            snapshot = save_snapshot(result, tmp)
            self.assertEqual(load_snapshot(snapshot), result)
            path = Path(tmp) / "output.json"
            write_reports(result, path, path.with_suffix(".xlsx"))
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), result)
            self.assertIn("benchmark_reserve", path.with_suffix(".txt").read_text(encoding="utf-8"))
            wb = load_workbook(path.with_suffix(".xlsx"), read_only=True)
            self.assertIn(("half_active_tilt", "status", "feasible"), list(wb["현재 추천"].values))
            wb.close()

    def test_comparison_table_matches_excel_numeric_cells_and_marks_window(self):
        data = inputs()
        with_holdings(data, {"CASH": 1})
        result = assess(data)
        history = result["portfolio_comparison"]["historical_risk"]
        history.update(shared_window=True, portfolios={"selected": {"status": "available", "first_date": "2026-01-05",
                       "last_date": "2026-09-08", "max_drawdown": -.105}})
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "report.json"
            text = write_reports(result, path, path.with_suffix(".xlsx"))
            self.assertLess(text.index("낙폭 관측 기간"), text.index("판단 | 상태"))
            self.assertIn("-10.50%", text)
            self.assertIn("공통 2026-01-05 ~ 2026-09-08", text)
            wb = load_workbook(path.with_suffix(".xlsx"))
            table = wb.active
            self.assertEqual(table.title, "배분안 비교")
            self.assertEqual(table["A2"].value, "제안 배분")
            self.assertEqual(table["B2"].value, "충족 (조건부)")
            for col, value in (("C", .25), ("D", .75), ("E", .00075), ("F", .047),
                               ("G", 1.047 * .99925 - 1), ("J", -.105)):
                self.assertAlmostEqual(table[f"{col}2"].value, value)
                self.assertEqual(table[f"{col}2"].number_format, "0.00%")
            self.assertEqual(table["K3"].value, "N/A")
            wb.close()

    def test_public_cli_preview_and_accidental_legacy_fallback(self):
        data = inputs()
        data["predict"]["research_shortlist"] = {"policy_id": "research_shortlist_v1", "candidates": []}
        data["predict"]["available_at"] = data["decision"]["input_cutoff"]
        data["decision"]["author"] = "test📈"
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            for key in ("predict", "analyses", "risk", "decision"):
                (folder / f"{key}.json").write_text(json.dumps(data[key]), encoding="utf-8")
            cmd = [sys.executable, str(SKILL / "scripts/generate_portfolio_report.py"), "--output-dir", str(folder / "outputs")]
            for opt, name in (("predict", "predict"), ("investor", "analyses"), ("risk", "risk")):
                cmd.extend([f"--{opt}-json", str(folder / f"{name}.json")])
            env = {**os.environ, "PYTHONIOENCODING": "cp949"}
            old = subprocess.run(cmd, capture_output=True, env=env)
            self.assertNotEqual(old.returncode, 0)
            self.assertIn(b"--decision-json", old.stderr)
            preview = subprocess.run([*cmd, "--decision-json", str(folder / "decision.json"), "--preview"], capture_output=True, env=env)
            self.assertEqual(preview.returncode, 0, preview.stderr)
            self.assertIn(b"half_active_tilt", preview.stdout)
            self.assertFalse((folder / "outputs").exists())


if __name__ == "__main__":
    unittest.main()
