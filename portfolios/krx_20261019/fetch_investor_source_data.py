#!/usr/bin/env python3
"""Collect investor-analysis source data for the KRX predict top 30 and ETF alternatives.

The output deliberately omits predict scores, signals and ranks so that each
investor perspective works from raw data only. Relevant news is included as
headline facts without the classifier's sentiment or confidence.
"""

from __future__ import annotations

import json
import math
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import FinanceDataReader as fdr
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
SKILL_SCRIPTS = ROOT / ".agents" / "skills" / "investor-analysis" / "scripts"
sys.path.insert(0, str(SKILL_SCRIPTS))

from data_fetcher import get_financial_metrics, get_market_cap, search_line_items  # noqa: E402


OUTPUT_DIR = Path(__file__).resolve().parent
PREDICT_PATH = OUTPUT_DIR / "krx_predict_final_v2.json"
TASKS_PATH = OUTPUT_DIR / "krx_news_tasks_v2.json"
CLASSIFICATIONS_PATH = OUTPUT_DIR / "krx_news_classifications_v2.json"
UNIVERSE_PATH = ROOT / ".claude" / "skills" / "predict" / "scripts" / ".cache" / "tickers_krx_2026-10-19.json"
OUTPUT_PATH = OUTPUT_DIR / "investor_source_data.json"
TOP_N = 30
ETF_TICKERS = {"069500": "KOSPI 200", "229200": "KOSDAQ 150"}
DECISION_EVENT_TYPES = {"market_price_recap", "routine_disclosure"}

LINE_ITEMS = [
    "revenue", "net_income", "operating_income", "gross_profit",
    "free_cash_flow", "operating_cash_flow", "capital_expenditure",
    "research_and_development", "total_debt", "shareholders_equity",
    "total_assets", "total_liabilities", "current_assets",
    "current_liabilities", "cash_and_equivalents",
]


def price_summary(ticker: str, start: str, end: str) -> dict:
    """1년 종가 요약. 지난주 급락을 볼 수 있도록 최근 고점 대비 낙폭과 1개월 변화를 함께 남긴다."""
    frame = fdr.DataReader(ticker, start, end)
    closes = frame["Close"].dropna()
    if closes.empty:
        return {"status": "unavailable"}
    last = float(closes.iloc[-1])
    one_month = closes[closes.index >= closes.index[-1] - pd.Timedelta(days=31)]
    return {
        "status": "ok",
        "provider": "FinanceDataReader",
        "first_date": str(closes.index[0].date()),
        "last_date": str(closes.index[-1].date()),
        "first_close": float(closes.iloc[0]),
        "last_close": last,
        "high_1y": float(closes.max()),
        "low_1y": float(closes.min()),
        "drawdown_from_1y_high": round(last / float(closes.max()) - 1, 4),
        "return_1y": round(last / float(closes.iloc[0]) - 1, 4),
        "return_1m": round(last / float(one_month.iloc[0]) - 1, 4),
    }


def relevant_news(ticker: str, tasks: dict, classifications: dict) -> list[dict]:
    """종목 관련 이벤트 기사만 사실로 넘긴다. 분류기의 sentiment·confidence는 넘기지 않는다."""
    articles = {a["article_index"]: a for a in tasks.get(ticker, [])}
    rows = []
    for item in classifications.get(ticker, []):
        if item["relevance"] != "relevant" or item["abstain"] or item["event_type"] in DECISION_EVENT_TYPES:
            continue
        article = articles.get(item["article_index"])
        if article:
            rows.append({
                "date": article["date"],
                "publisher": article.get("publisher"),
                "headline_excerpt": article["headline"],
                "link": article["link"],
                "event_type": item["event_type"],
            })
    return rows


def fetch_stock(ticker: str, analysis_date: str, listing: dict, news: list[dict]) -> dict:
    metrics = get_financial_metrics(ticker, analysis_date)
    line_items = search_line_items(ticker, LINE_ITEMS, analysis_date, period="annual", limit=5)
    return {
        "asset_type": "stock",
        "data_source": "investor-analysis/data_fetcher.py (DART annual filings + PyKRX/Naver valuation)",
        "current_snapshot": True,
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "profile": listing,
        "metrics": metrics,
        "annual_line_items": line_items,
        "line_items_note": "DART 연간 사업보고서 기준. 2026년 반기·분기 실적은 포함되지 않았다.",
        "market_cap_krw": get_market_cap(ticker, analysis_date),
        "price_1y": price_summary(ticker, "2025-10-17", analysis_date),
        "recent_relevant_news": news,
    }


def kospi200_concentration(predict: dict, universe: list[str], listing: dict) -> dict:
    """KOSPI 200 근사 집중도. 운용사 PDF가 아니라 이번 predict 시가총액(유동비율 미반영)으로 계산한다."""
    caps = {r["ticker"]: (r.get("market_cap") or {}).get("value") for r in predict["rankings"]}
    members = [t for t in universe if listing.get(t, {}).get("Market") == "KOSPI" and caps.get(t)]
    total = sum(caps[t] for t in members)
    ordered = sorted(members, key=lambda t: -caps[t])
    sectors: dict[str, float] = {}
    for t in members:
        sector = listing[t].get("Sector") or "Unknown"
        sectors[sector] = sectors.get(sector, 0.0) + caps[t] / total
    return {
        "basis": "approximation_full_market_cap_not_float_adjusted",
        "member_count_in_universe": len(members),
        "top10": [{"ticker": t, "name": listing[t]["Name"], "weight": round(caps[t] / total, 4)} for t in ordered[:10]],
        "top10_weight": round(sum(caps[t] for t in ordered[:10]) / total, 4),
        "sector_weights_top8": dict(sorted(((k, round(v, 4)) for k, v in sectors.items()), key=lambda x: -x[1])[:8]),
    }


def fetch_etf(ticker: str, index_name: str, etf_listing: dict, concentration: dict | None) -> dict:
    row = etf_listing.get(ticker, {})
    return {
        "asset_type": "etf",
        "data_source": "FinanceDataReader ETF/KR listing + FinanceDataReader prices",
        "current_snapshot": True,
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "profile": {
            "name": row.get("Name"),
            "tracked_index": index_name,
            "price": row.get("Price"),
            "nav": row.get("NAV"),
            "market_cap_100m_krw": row.get("MarCap"),
            "earning_rate_pct_as_reported": row.get("EarningRate"),
        },
        "price_1y": price_summary(ticker, "2025-10-17", "2026-10-19"),
        "index_concentration": concentration,
        "holdings_note": "운용사 PDF 구성 종목과 총보수는 이 단계에서 수집하지 않았다.",
    }


def clean(value):
    if isinstance(value, dict):
        return {key: clean(item) for key, item in value.items()}
    if isinstance(value, list):
        return [clean(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, pd.Timestamp):
        return str(value.date())
    return value


def main() -> None:
    predict = json.loads(PREDICT_PATH.read_text(encoding="utf-8"))
    analysis_date = predict["analysis_date"]
    tickers = [row["ticker"] for row in predict["rankings"][:TOP_N]]
    tasks = {t["ticker"]: t["articles"] for t in json.loads(TASKS_PATH.read_text(encoding="utf-8"))["tasks"]}
    classifications = {
        r["ticker"]: r["classifications"]
        for r in json.loads(CLASSIFICATIONS_PATH.read_text(encoding="utf-8"))["results"]
    }
    desc = fdr.StockListing("KRX-DESC")
    listing = {
        row["Code"]: {k: row[k] for k in ("Name", "Market", "Sector", "Industry", "ListingDate", "SettleMonth")}
        for row in desc.to_dict("records")
    }
    etf_listing = {row["Symbol"]: row for row in fdr.StockListing("ETF/KR").to_dict("records")}
    universe = json.loads(UNIVERSE_PATH.read_text(encoding="utf-8"))

    results: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {
            executor.submit(
                fetch_stock, t, analysis_date, listing.get(t, {}), relevant_news(t, tasks, classifications)
            ): t
            for t in tickers
        }
        for completed, future in enumerate(as_completed(futures), start=1):
            ticker = futures[future]
            try:
                results[ticker] = future.result()
                print(f"[{completed:02d}/{len(tickers)}] {ticker}: ok")
            except Exception as exc:  # keep per-ticker failures explicit
                results[ticker] = {"asset_type": "stock", "error": type(exc).__name__, "metrics": []}
                print(f"[{completed:02d}/{len(tickers)}] {ticker}: error {type(exc).__name__}")

    concentration = kospi200_concentration(predict, universe, listing)
    for ticker, index_name in ETF_TICKERS.items():
        try:
            results[ticker] = fetch_etf(ticker, index_name, etf_listing, concentration if ticker == "069500" else None)
            print(f"{ticker}: ok")
        except Exception as exc:
            results[ticker] = {"asset_type": "etf", "error": type(exc).__name__}
            print(f"{ticker}: error {type(exc).__name__}")

    payload = clean({
        "analysis_date": analysis_date,
        "currency": "KRW",
        "source": "independent_investor_analysis_data_fetch",
        "excluded_on_purpose": "predict scores, signals, ranks, news sentiment and other perspectives",
        "market_context": (
            "2026-10-12~16 한 주 동안 KOSPI가 14% 넘게 하락했고 10-19 종가는 5768.01(+1.76%)다. "
            "AI 투자 수익성 우려, 미국 9월 CPI 충격, 외국인 반도체 대형주 매도가 겹쳤다."
        ),
        "tickers": {t: results[t] for t in [*tickers, *ETF_TICKERS]},
    })
    OUTPUT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"saved: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
