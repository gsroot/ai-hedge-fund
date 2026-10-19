#!/usr/bin/env python3
"""Collect investor-analysis source data for the predict top 30 and ETF alternatives.

The output deliberately omits predict scores, signals and ranks so that each
investor perspective works from raw data only.
"""

from __future__ import annotations

import json
import math
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import yfinance as yf


ROOT = Path(__file__).resolve().parents[2]
SKILL_SCRIPTS = ROOT / ".agents" / "skills" / "investor-analysis" / "scripts"
sys.path.insert(0, str(SKILL_SCRIPTS))

from data_fetcher import get_financial_metrics, get_market_cap, search_line_items  # noqa: E402


OUTPUT_DIR = Path(__file__).resolve().parent
PREDICT_PATH = OUTPUT_DIR / "sp500_predict.json"
SPY_HOLDINGS_PATH = OUTPUT_DIR / "raw" / "ssga_spy_holdings.xlsx"
OUTPUT_PATH = OUTPUT_DIR / "investor_source_data.json"
TOP_N = 30
ETF_TICKERS = ("SPY", "VOO")

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
PROFILE_FIELDS = [
    "shortName", "longName", "sector", "industry", "longBusinessSummary",
    "currency", "financialCurrency", "regularMarketTime", "regularMarketPrice",
    "trailingPE", "forwardPE", "lastFiscalYearEnd", "mostRecentQuarter",
    "fiftyTwoWeekHigh", "fiftyTwoWeekLow", "dividendYield", "beta",
]
ETF_PROFILE_FIELDS = [
    "shortName", "longName", "longBusinessSummary", "fundFamily", "category",
    "netExpenseRatio", "annualReportExpenseRatio", "totalAssets", "yield",
    "trailingPE", "regularMarketPrice", "regularMarketTime",
    "fiftyTwoWeekHigh", "fiftyTwoWeekLow", "currency", "beta3Year",
]


def fetch_stock(ticker: str, analysis_date: str) -> dict:
    metrics = get_financial_metrics(ticker, analysis_date)
    line_items = search_line_items(
        ticker, LINE_ITEMS, analysis_date, period="annual", limit=5
    )
    info = yf.Ticker(ticker).info
    return {
        "asset_type": "stock",
        "data_source": "investor-analysis/data_fetcher.py (Yahoo Finance current snapshot)",
        "current_snapshot": True,
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "source_url": f"https://finance.yahoo.com/quote/{ticker}/financials/",
        "metrics": metrics,
        "line_items": line_items,
        "market_cap": get_market_cap(ticker, analysis_date),
        "profile": {key: info.get(key) for key in PROFILE_FIELDS},
    }


def spy_holdings_summary(sector_by_ticker: dict[str, str]) -> dict:
    frame = pd.read_excel(SPY_HOLDINGS_PATH, header=4)
    frame = frame[frame["Ticker"].notna() & frame["Weight"].notna()].copy()
    frame["Ticker"] = frame["Ticker"].astype(str).str.strip().str.replace(".", "-", regex=False)
    frame["weight"] = frame["Weight"].astype(float) / 100.0
    frame = frame.sort_values("weight", ascending=False)
    equities = frame[frame["Ticker"].str.match(r"^[A-Z][A-Z\-]*$")]
    sectors: dict[str, float] = {}
    for row in equities.itertuples():
        sector = sector_by_ticker.get(row.Ticker) or "Unknown"
        sectors[sector] = sectors.get(sector, 0.0) + row.weight
    return {
        "source": "https://www.ssga.com/library-content/products/fund-data/etfs/us/holdings-daily-us-en-spy.xlsx",
        "holdings_as_of": "2026-10-15",
        "holding_count": int(len(equities)),
        "top10": [
            {"ticker": row.Ticker, "name": row.Name, "weight": round(row.weight, 6)}
            for row in equities.head(10).itertuples()
        ],
        "top10_weight": round(float(equities.head(10)["weight"].sum()), 6),
        "sector_weights": {
            key: round(value, 6)
            for key, value in sorted(sectors.items(), key=lambda item: -item[1])
        },
        "sector_basis": "Yahoo sector of each holding from this run's predict snapshot",
    }


def fetch_etf(ticker: str, spy_summary: dict) -> dict:
    stock = yf.Ticker(ticker)
    info = stock.info
    history = stock.history(period="1y")
    closes = history["Close"].dropna() if not history.empty else pd.Series(dtype=float)
    payload = {
        "asset_type": "etf",
        "data_source": "Yahoo Finance current snapshot; holdings from SSGA SPY file",
        "current_snapshot": True,
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "profile": {key: info.get(key) for key in ETF_PROFILE_FIELDS},
        "price_1y": {
            "first_close": float(closes.iloc[0]) if len(closes) else None,
            "last_close": float(closes.iloc[-1]) if len(closes) else None,
            "first_date": str(closes.index[0].date()) if len(closes) else None,
            "last_date": str(closes.index[-1].date()) if len(closes) else None,
        },
        "tracked_index": "S&P 500",
        "holdings_note": (
            "SPY and VOO both track the S&P 500; the SSGA SPY holdings file is "
            "used as the constituent and concentration proxy for both."
        ),
        "index_holdings_summary": spy_summary,
    }
    return payload


def clean(value):
    if isinstance(value, dict):
        return {key: clean(item) for key, item in value.items()}
    if isinstance(value, list):
        return [clean(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def main() -> None:
    predict = json.loads(PREDICT_PATH.read_text(encoding="utf-8"))
    analysis_date = predict["analysis_date"]
    tickers = [row["ticker"] for row in predict["rankings"][:TOP_N]]
    sector_by_ticker = {
        row["ticker"]: (row.get("metrics") or {}).get("sector")
        for row in predict["rankings"]
    }
    results: dict[str, dict] = {}

    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {
            executor.submit(fetch_stock, ticker, analysis_date): ticker
            for ticker in tickers
        }
        for completed, future in enumerate(as_completed(futures), start=1):
            ticker = futures[future]
            try:
                results[ticker] = future.result()
                print(f"[{completed:02d}/{len(tickers)}] {ticker}: ok")
            except Exception as exc:  # keep per-ticker failures explicit
                results[ticker] = {
                    "asset_type": "stock",
                    "current_snapshot": True,
                    "error": type(exc).__name__,
                    "metrics": [],
                    "line_items": [],
                    "market_cap": None,
                }
                print(f"[{completed:02d}/{len(tickers)}] {ticker}: error {type(exc).__name__}")

    spy_summary = spy_holdings_summary(sector_by_ticker)
    for ticker in ETF_TICKERS:
        try:
            results[ticker] = fetch_etf(ticker, spy_summary)
            print(f"{ticker}: ok")
        except Exception as exc:
            results[ticker] = {"asset_type": "etf", "error": type(exc).__name__}
            print(f"{ticker}: error {type(exc).__name__}")

    ordered = {ticker: results[ticker] for ticker in [*tickers, *ETF_TICKERS]}
    payload = clean({
        "analysis_date": analysis_date,
        "source": "independent_investor_analysis_data_fetch",
        "excluded_on_purpose": "predict scores, signals, ranks and other perspectives",
        "tickers": ordered,
    })
    OUTPUT_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    print(f"saved: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
