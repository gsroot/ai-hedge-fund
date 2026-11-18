"""Provider boundary cases shared by research rankings and portfolio risk."""
from datetime import date
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / ".agents/skills/predict/scripts"))
import data_fetcher as prices


class PriceCutoffTests(unittest.TestCase):
    def test_yahoo_end_includes_historic_session_and_avoids_unfinished_daily_bar(self):
        today = date(2025, 1, 2)
        self.assertEqual(prices._yahoo_exclusive_end("2024-12-31", today), "2025-01-01")
        self.assertEqual(prices._yahoo_exclusive_end("2025-01-02", today), "2025-01-02")
        self.assertEqual(prices._yahoo_exclusive_end("2025-01-04", today), "2025-01-02")

    def test_single_and_yahoo_batch_return_same_last_close_and_provider(self):
        end = "2024-12-31"
        frame = pd.DataFrame({"Open": [101], "High": [103], "Low": [100], "Close": [102], "Volume": [42]},
                             index=pd.to_datetime([end]))
        grouped = pd.concat({"AAA": frame}, axis=1)
        with patch.object(prices, "safe_get_ticker_history", return_value=frame) as single:
            result = prices._fetch_prices_yf("AAA", "2024-12-30", end)
        with patch.object(prices, "safe_batch_download", return_value=grouped) as bulk:
            batch = prices.batch_fetch_prices(["AAA"], "2024-12-30", end)
        self.assertEqual(result, batch["AAA"])
        self.assertEqual((result[0]["time"], result[0]["provider"]), (end, "yahoo_finance"))
        self.assertEqual(single.call_args.args[-1], "2025-01-01")
        self.assertEqual(bulk.call_args.kwargs["end"], "2025-01-01")

    def test_measured_zero_and_missing_yahoo_fields_remain_distinct(self):
        for raw in (0, None):
            info = {"debtToEquity": raw, "freeCashflow": raw, "sharesOutstanding": 20, "marketCap": 100}
            with patch.object(prices, "safe_get_ticker_info", return_value=info), patch.object(prices, "_calculate_derived_metrics", return_value={}):
                observed = prices._fetch_financial_metrics_yf("AAA")
            for key in ("debt_to_equity", "free_cash_flow_yield", "free_cash_flow_per_share"):
                self.assertEqual(observed[key], raw)

    def test_yahoo_yield_in_percentage_points_normalized_even_below_one_percent(self):
        for percent in (0, .4, 2.15, None):
            with patch.object(prices, "safe_get_ticker_info", return_value={"dividendYield": percent}), patch.object(prices, "_calculate_derived_metrics", return_value={}):
                observed = prices._fetch_financial_metrics_yf("AAA")
            self.assertEqual(observed["dividend_yield"], percent / 100 if percent is not None else None)
