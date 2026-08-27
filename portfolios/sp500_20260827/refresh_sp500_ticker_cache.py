#!/usr/bin/env python3
"""Refresh the same-day S&P 500 constituent cache from Wikipedia's table."""

from __future__ import annotations

import io
import json
from pathlib import Path

import pandas as pd
import requests


ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIR = Path(__file__).resolve().parent
ANALYSIS_DATE = "2026-08-27"
URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
CACHE_PATH = (
    ROOT
    / ".agents"
    / "skills"
    / "predict"
    / "scripts"
    / ".cache"
    / f"tickers_sp500_{ANALYSIS_DATE}.json"
)
SNAPSHOT_PATH = OUTPUT_DIR / f"sp500_constituents_{ANALYSIS_DATE.replace('-', '')}.json"


def main() -> None:
    response = requests.get(
        URL,
        headers={"User-Agent": "Mozilla/5.0 (compatible; StockAnalyzer/1.0)"},
        timeout=30,
    )
    response.raise_for_status()
    table = pd.read_html(io.StringIO(response.text))[0]
    tickers = [str(value).strip().replace(".", "-") for value in table["Symbol"]]
    tickers = list(dict.fromkeys(tickers))
    if not 500 <= len(tickers) <= 505:
        raise ValueError(f"unexpected constituent count: {len(tickers)}")

    payload = {
        "analysis_date": ANALYSIS_DATE,
        "source": URL,
        "retrieved_live": True,
        "count": len(tickers),
        "tickers": tickers,
    }
    SNAPSHOT_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(tickers, indent=2), encoding="utf-8")
    print(f"saved {len(tickers)} constituents: {SNAPSHOT_PATH}")
    print(f"updated predict cache: {CACHE_PATH}")


if __name__ == "__main__":
    main()
