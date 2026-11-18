import io
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

import pandas as pd

SKILLS = Path(__file__).resolve().parents[1] / ".agents/skills"
sys.path[:0] = [str(SKILLS / f"{skill}/scripts") for skill in ("predict", "backtesting")]
import analysis
import backtest


class HistoricalCohortTests(unittest.TestCase):
    def setUp(self):
        self.days = pd.bdate_range(end="2024-01-31", periods=65)
        self.cutoff = str(self.days[-1].date())
        self.tickers = ["000001", "000002", "000003"]
        self.bars = [{"time": str(day.date()), "close": float(100 + i)} for i, day in enumerate(self.days)]
        self.frame = pd.DataFrame({("Close", t): [b["close"] for b in self.bars] for t in self.tickers}, index=self.days)

    def run_signal(self, hybrid=False):
        def financials(ticker, *args, **kwargs):
            if ticker == self.tickers[-1]:
                return []
            return [{"price_to_book_ratio": 10 if ticker == self.tickers[0] else 1, "return_on_equity": .15}]

        prices = dict.fromkeys(self.tickers, self.bars)
        with patch.object(analysis, "batch_fetch_prices", return_value=prices), \
                patch.object(analysis, "get_financial_metrics", side_effect=financials), \
                patch.object(analysis, "get_prices", side_effect=AssertionError), \
                patch.object(analysis, "get_company_news", side_effect=AssertionError), \
                patch.object(analysis, "get_insider_trades", side_effect=AssertionError), \
                patch.object(backtest, "generate_momentum_signals", side_effect=AssertionError):
            if hybrid:
                return backtest.generate_hybrid_signals(self.tickers, self.cutoff, self.frame, skip_news=True)
            return backtest.generate_signals_from_predictor(self.tickers, self.cutoff, skip_news=True)

    def test_predictor_uses_cross_section_and_excludes_failed_companies(self):
        signals = self.run_signal()
        self.assertGreater(signals["000002"]["score"], signals["000001"]["score"])
        self.assertEqual(signals["000002"]["action"], backtest.Action.BUY)
        self.assertEqual(signals["000003"]["excluded_reason"], "metrics_unavailable")
        self.assertNotIn("action", signals["000003"])

    def test_hybrid_uses_shared_financial_ranks_and_only_preformation_prices(self):
        self.frame.loc[pd.Timestamp("2024-02-01")] = [999, 0, 999]
        signals = self.run_signal(hybrid=True)
        self.assertGreater(signals["000002"]["fundamental_score"], signals["000001"]["fundamental_score"])
        self.assertEqual(signals["000002"]["momentum_score"], signals["000001"]["momentum_score"])
        self.assertNotIn("rank", signals["000003"])
        self.frame.loc[self.days[:-3], ("Close", "000002")] = float("nan")
        self.assertIn("excluded_reason", self.run_signal(hybrid=True)["000002"])

    def test_next_open_is_checked_only_when_executing_frozen_ranks(self):
        execution_day = pd.Timestamp("2024-02-01")
        frame = self.frame.copy()
        for t in self.tickers:
            frame["Open", t] = frame["Close", t]
        frame.loc[execution_day] = frame.iloc[-1]
        frame.loc[execution_day, ("Open", "000002")] = float("nan")
        engine = backtest.BacktestEngine(self.tickers, "2024-02-01", "2024-02-01", benchmark="", strategy="predictor")
        signals = {"000002": {"action": backtest.Action.BUY, "confidence": 1, "score": 9}}
        with patch.object(engine, "_fetch_price_data", return_value=frame), \
                patch.object(backtest, "generate_signals_from_predictor", return_value=signals) as collect, \
                redirect_stdout(io.StringIO()):
            result = engine.run()
        self.assertEqual(collect.call_args.args, (self.tickers, self.cutoff))
        self.assertFalse(result["trade_history"])
