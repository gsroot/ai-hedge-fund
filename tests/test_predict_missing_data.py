from __future__ import annotations

import importlib.util
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1]
PREDICT_SCRIPTS = ROOT / ".agents" / "skills" / "predict" / "scripts"

if str(PREDICT_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(PREDICT_SCRIPTS))


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


predict_data = load_module(
    "missing_data_predict_data", PREDICT_SCRIPTS / "data_fetcher.py"
)
predict_analysis = load_module(
    "missing_data_predict_analysis", PREDICT_SCRIPTS / "analysis.py"
)

TODAY = datetime.now().strftime("%Y-%m-%d")
NULL_METRICS = {
    "ticker": "WBA",
    "company_name": "WBA",
    "market_cap": None,
    "price_to_earnings_ratio": None,
    "price_to_book_ratio": None,
    "return_on_equity": None,
    "operating_margin": None,
    "revenue_growth": None,
    "total_revenue": None,
}
USABLE_METRICS = {**NULL_METRICS, "ticker": "AAPL", "market_cap": 3.0e12}


class UsableMetricsGateTests(unittest.TestCase):
    def test_all_null_skeleton_is_not_usable(self):
        self.assertFalse(predict_data.has_usable_metrics(NULL_METRICS))
        self.assertFalse(predict_data.has_usable_metrics(None))
        self.assertFalse(predict_data.has_usable_metrics({}))
        self.assertTrue(predict_data.has_usable_metrics(USABLE_METRICS))

    def test_nan_and_inf_count_as_missing(self):
        nan_metrics = {**NULL_METRICS, "market_cap": float("nan")}
        inf_metrics = {**NULL_METRICS, "price_to_earnings_ratio": float("inf")}
        self.assertFalse(predict_data.has_usable_metrics(nan_metrics))
        self.assertFalse(predict_data.has_usable_metrics(inf_metrics))

    def test_null_us_snapshot_is_missing_and_not_cached(self):
        write_cache = Mock()
        with patch.object(predict_data, "_read_cache", return_value=None), \
                patch.object(predict_data, "_write_cache", write_cache), \
                patch.object(
                    predict_data,
                    "_fetch_financial_metrics_yf",
                    return_value=dict(NULL_METRICS),
                ), \
                patch(
                    "financial_datasets_api.get_metrics_snapshot_fallback",
                    return_value=None,
                ):
            result = predict_data.get_financial_metrics("WBA", TODAY)

        self.assertEqual(result, [])
        write_cache.assert_not_called()

    def test_cached_null_snapshot_is_treated_as_cache_miss(self):
        write_cache = Mock()
        fetch = Mock(return_value=dict(USABLE_METRICS))
        with patch.object(
            predict_data, "_read_cache", return_value=dict(NULL_METRICS)
        ), patch.object(predict_data, "_write_cache", write_cache), \
                patch.object(predict_data, "_fetch_financial_metrics_yf", fetch):
            result = predict_data.get_financial_metrics("AAPL", TODAY)

        self.assertEqual(result, [USABLE_METRICS])
        fetch.assert_called_once_with("AAPL")
        write_cache.assert_called_once()


class ExclusionReasonTests(unittest.TestCase):
    def _detailed(self, **patches):
        defaults = {
            "get_financial_metrics": Mock(return_value=[dict(USABLE_METRICS)]),
            "get_prices": Mock(return_value=[]),
            "get_insider_trades": Mock(return_value=[]),
            "get_company_news": Mock(return_value=[]),
        }
        defaults.update(patches)
        with patch.multiple(predict_analysis, **defaults):
            return predict_analysis.analyze_single_ticker_detailed(
                "AAPL", TODAY, skip_news=True
            )

    def test_missing_metrics_are_excluded_with_reason(self):
        result, reason = self._detailed(
            get_financial_metrics=Mock(return_value=[])
        )
        self.assertIsNone(result)
        self.assertEqual(reason, "metrics_unavailable")

    def test_missing_prices_are_excluded_instead_of_scored_as_zero(self):
        result, reason = self._detailed(get_prices=Mock(return_value=[]))
        self.assertIsNone(result)
        self.assertEqual(reason, "prices_unavailable")

    def test_unexpected_errors_record_type_not_message(self):
        result, reason = self._detailed(
            get_financial_metrics=Mock(side_effect=KeyError("secret-ish detail"))
        )
        self.assertIsNone(result)
        self.assertEqual(reason, "analysis_error:KeyError")
        self.assertNotIn("secret-ish", reason)

    def test_legacy_wrapper_keeps_returning_only_the_result(self):
        with patch.object(
            predict_analysis,
            "analyze_single_ticker_detailed",
            return_value=(None, "metrics_unavailable"),
        ):
            self.assertIsNone(
                predict_analysis.analyze_single_ticker("WBA", TODAY)
            )


class BatchExclusionTests(unittest.TestCase):
    def test_batch_ranks_only_analyzed_and_lists_exclusions(self):
        outcomes = {
            "AAA": ({"ticker": "AAA", "total_score": 5.0}, None),
            "BBB": ({"ticker": "BBB", "total_score": 7.0}, None),
            "WBA": (None, "metrics_unavailable"),
            "IPG": (None, "prices_unavailable"),
        }

        def fake_detailed(ticker, *_args, **_kwargs):
            return outcomes[ticker]

        with patch.multiple(
            predict_analysis,
            batch_fetch_prices=Mock(return_value={}),
            get_financial_metrics=Mock(return_value=[]),
            calculate_sector_stats=Mock(return_value={}),
            analyze_single_ticker_detailed=Mock(side_effect=fake_detailed),
        ):
            batch = predict_analysis.run_batch_analysis_with_exclusions(
                list(outcomes), TODAY, max_workers=1
            )

        self.assertEqual([r["ticker"] for r in batch.results], ["BBB", "AAA"])
        self.assertEqual([r["rank"] for r in batch.results], [1, 2])
        self.assertEqual(
            batch.excluded,
            (
                {"ticker": "IPG", "reason": "prices_unavailable"},
                {"ticker": "WBA", "reason": "metrics_unavailable"},
            ),
        )
        self.assertEqual(
            predict_analysis.summarize_exclusions(batch.excluded),
            {"metrics_unavailable": 1, "prices_unavailable": 1},
        )


class UniverseProvenanceTests(unittest.TestCase):
    def test_wikipedia_failure_is_marked_as_stale_static_fallback(self):
        with patch.object(
            predict_data, "fetch_sp500_tickers_from_wikipedia", return_value=None
        ):
            universe = predict_data.resolve_index_universe("sp500", use_cache=False)

        self.assertEqual(universe.source, "fallback_static")
        self.assertTrue(universe.may_be_stale)
        self.assertGreater(len(universe.tickers), 400)

    def test_live_wikipedia_list_is_marked_live(self):
        with patch.object(
            predict_data,
            "fetch_sp500_tickers_from_wikipedia",
            return_value=["AAPL", "MSFT"],
        ):
            universe = predict_data.resolve_index_universe("sp500", use_cache=False)

        self.assertEqual(universe.source, "wikipedia")
        self.assertFalse(universe.may_be_stale)
        self.assertEqual(universe.tickers, ("AAPL", "MSFT"))

    def test_same_day_cache_is_labelled_as_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache_file = Path(tmp) / f"tickers_sp500_{TODAY}.json"
            cache_file.write_text('["AAPL"]', encoding="utf-8")
            with patch.object(predict_data, "CACHE_DIR", tmp), \
                    patch.object(predict_data, "CACHE_ENABLED", True):
                universe = predict_data.resolve_index_universe("sp500")

        self.assertEqual(universe.source, "daily_cache")
        self.assertEqual(universe.tickers, ("AAPL",))

    def test_empty_same_day_cache_is_a_miss(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache_file = Path(tmp) / f"tickers_sp500_{TODAY}.json"
            cache_file.write_text("[]", encoding="utf-8")
            with patch.object(predict_data, "CACHE_DIR", tmp), \
                    patch.object(predict_data, "CACHE_ENABLED", True), \
                    patch.object(
                        predict_data,
                        "fetch_sp500_tickers_from_wikipedia",
                        return_value=["AAPL"],
                    ):
                universe = predict_data.resolve_index_universe("sp500")

        self.assertEqual(universe.source, "wikipedia")

    def test_legacy_get_index_tickers_still_returns_a_list(self):
        with patch.object(
            predict_data,
            "fetch_sp500_tickers_from_wikipedia",
            return_value=["AAPL"],
        ):
            tickers = predict_data.get_index_tickers("sp500", use_cache=False)

        self.assertEqual(tickers, ["AAPL"])


predict_cli = load_module(
    "missing_data_predict_cli", PREDICT_SCRIPTS / "analyze_stocks.py"
)


class PredictCliOutputTests(unittest.TestCase):
    def test_backtest_can_still_import_get_index_tickers(self):
        # backtesting/scripts/backtest.py: from analyze_stocks import get_index_tickers
        self.assertTrue(callable(predict_cli.get_index_tickers))

    def test_all_excluded_run_still_writes_exclusions_and_fails(self):
        universe = predict_data.IndexUniverse(("WBA", "IPG"), "fallback_static", True)
        batch = predict_analysis.BatchAnalysis(
            results=(),
            excluded=({"ticker": "WBA", "reason": "metrics_unavailable"},),
        )
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "out.json"
            argv = [
                "analyze_stocks.py", "--index", "sp500", "--top", "1",
                "--no-sort-by-cap", "--output", str(output),
            ]
            with patch.object(sys, "argv", argv), \
                    patch.object(predict_cli, "resolve_index_universe", return_value=universe), \
                    patch.object(
                        predict_cli,
                        "run_batch_analysis_with_exclusions",
                        return_value=batch,
                    ), \
                    redirect_stdout(io.StringIO()):
                with self.assertRaises(SystemExit) as raised:
                    predict_cli.main()
            data = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(raised.exception.code, 1)
        self.assertEqual(data["rankings"], [])
        self.assertEqual(
            data["universe"],
            {
                "source": "fallback_static",
                "may_be_stale": True,
                "size": 2,
                "requested_count": 1,
            },
        )
        self.assertEqual(data["total_excluded"], 1)
        self.assertEqual(data["exclusion_summary"], {"metrics_unavailable": 1})


if __name__ == "__main__":
    unittest.main()
