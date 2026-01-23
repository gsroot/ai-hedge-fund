#!/usr/bin/env python3
"""
Financial Data Fetcher

기존 src/tools/api.py를 래핑하여 투자 분석에 필요한 데이터를 수집합니다.
"""
import sys
import os
import argparse
from datetime import datetime, timedelta

# 프로젝트 루트를 경로에 추가
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
sys.path.insert(0, project_root)

from src.tools.api import (
    get_financial_metrics,
    get_market_cap,
    search_line_items,
    get_insider_trades,
    get_company_news,
    get_prices,
)


def fetch_value_investor_data(ticker: str, end_date: str, api_key: str = None) -> dict:
    """가치 투자자(버핏, 그레이엄, 멍거, 파브라이)에게 필요한 데이터 수집."""
    metrics = get_financial_metrics(ticker, end_date, period="annual", limit=5, api_key=api_key)

    line_items = search_line_items(
        ticker,
        [
            "revenue", "net_income", "operating_income", "gross_profit",
            "free_cash_flow", "operating_cash_flow", "capital_expenditure",
            "depreciation_and_amortization", "total_debt", "shareholders_equity",
            "total_assets", "total_liabilities", "current_assets", "current_liabilities",
            "cash_and_equivalents", "book_value_per_share", "earnings_per_share",
            "outstanding_shares",
        ],
        end_date,
        period="annual",
        limit=5,
        api_key=api_key,
    )

    market_cap = get_market_cap(ticker, end_date, api_key=api_key)

    return {
        "metrics": metrics,
        "line_items": line_items,
        "market_cap": market_cap,
    }


def fetch_growth_investor_data(ticker: str, end_date: str, api_key: str = None) -> dict:
    """성장 투자자(캐시우드, 린치, 피셔)에게 필요한 데이터 수집."""
    metrics = get_financial_metrics(ticker, end_date, period="annual", limit=5, api_key=api_key)

    line_items = search_line_items(
        ticker,
        [
            "revenue", "net_income", "gross_profit", "operating_income",
            "research_and_development", "free_cash_flow",
            "earnings_per_share", "outstanding_shares",
            "selling_general_and_administrative",
        ],
        end_date,
        period="annual",
        limit=5,
        api_key=api_key,
    )

    market_cap = get_market_cap(ticker, end_date, api_key=api_key)

    return {
        "metrics": metrics,
        "line_items": line_items,
        "market_cap": market_cap,
    }


def fetch_technical_data(ticker: str, end_date: str, lookback_days: int = 252, api_key: str = None) -> dict:
    """기술적 분석에 필요한 가격 데이터 수집."""
    end_dt = datetime.strptime(end_date, "%Y-%m-%d")
    start_dt = end_dt - timedelta(days=lookback_days)
    start_date = start_dt.strftime("%Y-%m-%d")

    prices = get_prices(ticker, start_date, end_date, api_key=api_key)

    return {
        "prices": prices,
        "start_date": start_date,
        "end_date": end_date,
    }


def fetch_sentiment_data(ticker: str, end_date: str, api_key: str = None) -> dict:
    """센티먼트 분석에 필요한 데이터 수집."""
    insider_trades = get_insider_trades(ticker, end_date, limit=1000, api_key=api_key)
    company_news = get_company_news(ticker, end_date, limit=100, api_key=api_key)

    return {
        "insider_trades": insider_trades,
        "company_news": company_news,
    }


def fetch_all_data(ticker: str, end_date: str, api_key: str = None) -> dict:
    """모든 투자자/분석가에게 필요한 전체 데이터 수집."""
    value_data = fetch_value_investor_data(ticker, end_date, api_key)
    growth_data = fetch_growth_investor_data(ticker, end_date, api_key)
    technical_data = fetch_technical_data(ticker, end_date, api_key=api_key)
    sentiment_data = fetch_sentiment_data(ticker, end_date, api_key)

    return {
        "ticker": ticker,
        "end_date": end_date,
        "financial_metrics": value_data["metrics"],
        "line_items": value_data["line_items"],
        "market_cap": value_data["market_cap"],
        "prices": technical_data["prices"],
        "insider_trades": sentiment_data["insider_trades"],
        "company_news": sentiment_data["company_news"],
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fetch financial data for analysis")
    parser.add_argument("--ticker", type=str, required=True, help="Stock ticker (e.g., AAPL)")
    parser.add_argument("--end-date", type=str, default=None, help="End date (YYYY-MM-DD)")
    parser.add_argument("--data-type", type=str, default="all",
                       choices=["all", "value", "growth", "technical", "sentiment"],
                       help="Type of data to fetch")

    args = parser.parse_args()

    end_date = args.end_date or datetime.now().strftime("%Y-%m-%d")
    api_key = os.getenv("FINANCIAL_DATASETS_API_KEY")

    if args.data_type == "all":
        data = fetch_all_data(args.ticker, end_date, api_key)
    elif args.data_type == "value":
        data = fetch_value_investor_data(args.ticker, end_date, api_key)
    elif args.data_type == "growth":
        data = fetch_growth_investor_data(args.ticker, end_date, api_key)
    elif args.data_type == "technical":
        data = fetch_technical_data(args.ticker, end_date, api_key=api_key)
    elif args.data_type == "sentiment":
        data = fetch_sentiment_data(args.ticker, end_date, api_key)

    import json
    print(json.dumps(data, indent=2, default=str))
