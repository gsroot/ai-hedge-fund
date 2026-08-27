#!/usr/bin/env python3
"""Collect current investor-analysis source data for the predict top 30."""

from __future__ import annotations

import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SKILL_SCRIPTS = ROOT / ".agents" / "skills" / "investor-analysis" / "scripts"
sys.path.insert(0, str(SKILL_SCRIPTS))

from data_fetcher import get_financial_metrics, get_market_cap, search_line_items  # noqa: E402


OUTPUT_DIR = Path(__file__).resolve().parent
PREDICT_PATH = OUTPUT_DIR / "sp500_predict.json"
OUTPUT_PATH = OUTPUT_DIR / "investor_source_data.json"

LINE_ITEMS = [
    "revenue",
    "net_income",
    "operating_income",
    "gross_profit",
    "free_cash_flow",
    "operating_cash_flow",
    "capital_expenditure",
    "depreciation_and_amortization",
    "research_and_development",
    "selling_general_and_administrative",
    "total_debt",
    "shareholders_equity",
    "total_assets",
    "total_liabilities",
    "current_assets",
    "current_liabilities",
    "cash_and_equivalents",
]


def fetch_ticker(ticker: str, analysis_date: str) -> tuple[str, dict]:
    metrics = get_financial_metrics(ticker, analysis_date)
    line_items = search_line_items(
        ticker,
        LINE_ITEMS,
        analysis_date,
        period="annual",
        limit=5,
    )
    market_cap = get_market_cap(ticker, analysis_date)
    return ticker, {
        "analysis_date": analysis_date,
        "data_source": "investor-analysis/data_fetcher.py (Yahoo Finance current snapshot)",
        "current_snapshot": True,
        "metrics": metrics,
        "line_items": line_items,
        "market_cap": market_cap,
    }


def main() -> None:
    predict = json.loads(PREDICT_PATH.read_text(encoding="utf-8"))
    analysis_date = predict["analysis_date"]
    tickers = [row["ticker"] for row in predict["rankings"][:30]]
    results: dict[str, dict] = {}

    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {
            executor.submit(fetch_ticker, ticker, analysis_date): ticker
            for ticker in tickers
        }
        for completed, future in enumerate(as_completed(futures), start=1):
            ticker = futures[future]
            try:
                fetched_ticker, data = future.result()
                results[fetched_ticker] = data
                print(f"[{completed:02d}/{len(tickers)}] {ticker}: ok")
            except Exception as exc:  # keep per-ticker failures explicit
                results[ticker] = {
                    "analysis_date": analysis_date,
                    "data_source": "investor-analysis/data_fetcher.py (Yahoo Finance current snapshot)",
                    "current_snapshot": True,
                    "error": str(exc),
                    "metrics": [],
                    "line_items": [],
                    "market_cap": None,
                }
                print(f"[{completed:02d}/{len(tickers)}] {ticker}: error: {exc}")

    ordered = {ticker: results[ticker] for ticker in tickers}
    payload = {
        "analysis_date": analysis_date,
        "source": "independent_investor_analysis_data_fetch",
        "tickers": ordered,
    }
    OUTPUT_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    print(f"saved: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
