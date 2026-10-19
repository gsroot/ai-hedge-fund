from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PREDICT_SCRIPTS = ROOT / ".agents" / "skills" / "predict" / "scripts"
CLAUDE_PREDICT_SCRIPTS = ROOT / ".claude" / "skills" / "predict" / "scripts"

if str(PREDICT_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(PREDICT_SCRIPTS))


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


investor_scoring = load_module(
    "market_cap_investor_scoring", PREDICT_SCRIPTS / "investor_scoring.py"
)

HIGH_LYNCH = {"lynch": 8.4}
KRW_JO = 1e12


def lynch_metrics(ticker: str, market_cap: float | None) -> dict:
    return {
        "ticker": ticker,
        "market_cap": market_cap,
        "price_to_earnings_ratio": 15.0,
        "revenue_growth": 0.25,
        "earnings_growth": 0.30,
        "return_on_equity": 0.20,
    }


class LynchSizeAdjustmentTests(unittest.TestCase):
    def test_usd_tiers_include_small_cap_bonus(self):
        cases = [(300e9, -0.8), (150e9, -0.3), (50e9, 0), (5e9, 0.5), (1e9, 1.0)]
        for market_cap, expected in cases:
            with self.subTest(market_cap=market_cap):
                self.assertEqual(
                    investor_scoring.lynch_size_adjustment(market_cap), expected
                )

    def test_krw_caps_use_won_thresholds(self):
        cases = [
            (300 * KRW_JO, -0.8),
            (150 * KRW_JO, -0.3),
            (50 * KRW_JO, 0),
            (5 * KRW_JO, 0.5),
            (1.4 * KRW_JO, 1.0),
        ]
        for market_cap, expected in cases:
            with self.subTest(market_cap=market_cap):
                self.assertEqual(
                    investor_scoring.lynch_size_adjustment(market_cap, currency="KRW"),
                    expected,
                )

    def test_tier_boundaries_are_exclusive(self):
        cases = [(200e9, -0.3), (100e9, 0), (10e9, 0), (2e9, 0.5)]
        for market_cap, expected in cases:
            with self.subTest(market_cap=market_cap):
                self.assertEqual(
                    investor_scoring.lynch_size_adjustment(market_cap), expected
                )
                self.assertEqual(
                    investor_scoring.lynch_size_adjustment(
                        market_cap * 1000, currency="KRW"
                    ),
                    expected,
                )

    def test_missing_cap_is_not_adjusted(self):
        self.assertEqual(investor_scoring.lynch_size_adjustment(None), 0)
        self.assertEqual(investor_scoring.lynch_size_adjustment(0, currency="KRW"), 0)

    def test_korean_small_cap_is_not_penalized_as_mega_cap(self):
        small = investor_scoring.calculate_lynch_score(
            [lynch_metrics("039200", 1.4 * KRW_JO)], 6, 5, 5
        )
        mega = investor_scoring.calculate_lynch_score(
            [lynch_metrics("039200", 300 * KRW_JO)], 6, 5, 5
        )
        self.assertAlmostEqual(small - mega, 1.8)


class MegaCapWarningTests(unittest.TestCase):
    def test_korean_small_cap_has_no_mega_cap_warning(self):
        warnings = investor_scoring.generate_investor_warnings(
            "039200", HIGH_LYNCH, lynch_metrics("039200", 1.4 * KRW_JO)
        )
        self.assertFalse([w for w in warnings if "메가캡" in w])

    def test_korean_suffixed_ticker_uses_won(self):
        warnings = investor_scoring.generate_investor_warnings(
            "039200.KQ", HIGH_LYNCH, lynch_metrics("039200.KQ", 5 * KRW_JO)
        )
        self.assertFalse([w for w in warnings if "메가캡" in w])

    def test_cash_flow_warnings_use_market_currency(self):
        krw = investor_scoring.generate_investor_warnings(
            "039200", {}, {"operating_cashflow": -120e8, "free_cash_flow": -150e8}
        )
        usd = investor_scoring.generate_investor_warnings(
            "AAPL", {}, {"operating_cashflow": 10e6, "free_cash_flow": -25e6}
        )
        self.assertIn("🚨 영업현금흐름 마이너스 (₩-120억) - 본업 현금소진", krw)
        self.assertIn("⚠️ FCF 마이너스 ($-25M) - 높은 CapEx 부담", usd)

    def test_korean_mega_cap_warning_shows_won(self):
        warnings = investor_scoring.generate_investor_warnings(
            "000660", HIGH_LYNCH, lynch_metrics("000660", 880 * KRW_JO)
        )
        self.assertIn("⚠️ Lynch 높은점수(8.4) but 메가캡(₩880조, 10배 어려움)", warnings)

    def test_us_mega_cap_warning_shows_dollars(self):
        warnings = investor_scoring.generate_investor_warnings(
            "AAPL", HIGH_LYNCH, lynch_metrics("AAPL", 300e9)
        )
        self.assertIn("⚠️ Lynch 높은점수(8.4) but 메가캡($300B, 10배 어려움)", warnings)


class PlatformParityTests(unittest.TestCase):
    def test_claude_and_codex_copies_match(self):
        for name in ("investor_scoring.py", "factor_scoring.py"):
            with self.subTest(name=name):
                self.assertEqual(
                    (PREDICT_SCRIPTS / name).read_bytes(),
                    (CLAUDE_PREDICT_SCRIPTS / name).read_bytes(),
                )


if __name__ == "__main__":
    unittest.main()
