#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd


PREDICT_SCRIPTS = Path(__file__).resolve().parents[2] / "predict" / "scripts"
if str(PREDICT_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(PREDICT_SCRIPTS))

from data_fetcher import get_prices  # noqa: E402


def build_risk_snapshot(
    tickers: list[str],
    analysis_date: str,
    lookback_days: int = 400,
    min_observations: int = 60,
) -> dict:
    end_dt = datetime.strptime(analysis_date, "%Y-%m-%d")
    start_date = (end_dt - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
    close_series = {}
    dropped = {}
    for ticker in tickers:
        rows = get_prices(ticker, start_date, analysis_date)
        values = {
            pd.Timestamp(row["date"]): float(row["close"])
            for row in rows
            if row.get("date") and row.get("close") is not None
        }
        series = pd.Series(values, dtype=float).sort_index()
        if len(series) < min_observations + 1:
            dropped[ticker] = f"가격 관측치 부족 ({len(series)})"
            continue
        close_series[ticker] = series

    if not close_series:
        raise ValueError("변동성 계산에 필요한 가격 데이터가 없습니다.")

    prices = pd.DataFrame(close_series).sort_index()
    returns = prices.pct_change(fill_method=None)
    valid = {
        ticker: series.dropna()
        for ticker, series in returns.items()
        if series.dropna().shape[0] >= min_observations
    }
    for ticker in set(close_series) - set(valid):
        dropped[ticker] = "수익률 관측치 부족"
    if not valid:
        raise ValueError("최소 관측치를 충족한 종목이 없습니다.")

    returns = pd.DataFrame(valid)
    annualized_volatility = {
        ticker: float(series.std(ddof=1) * math.sqrt(252))
        for ticker, series in returns.items()
    }
    correlation_df = returns.corr(min_periods=min_observations)
    correlation = {
        ticker: {
            peer: float(value)
            for peer, value in correlation_df[ticker].items()
            if pd.notna(value)
        }
        for ticker in correlation_df.columns
    }
    return {
        "analysis_date": analysis_date,
        "lookback_start": start_date,
        "min_observations": min_observations,
        "annualized_volatility": annualized_volatility,
        "correlation": correlation,
        "dropped": dropped,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="predict 후보의 point-in-time 변동성·상관 스냅샷 생성")
    parser.add_argument("--predict-json", required=True)
    parser.add_argument("--top", type=int, default=30)
    parser.add_argument("--lookback-days", type=int, default=400)
    parser.add_argument("--min-observations", type=int, default=60)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    payload = json.loads(Path(args.predict_json).read_text(encoding="utf-8"))
    analysis_date = payload.get("analysis_date")
    if not analysis_date:
        parser.error("predict JSON에 analysis_date가 없습니다.")
    tickers = [item["ticker"] for item in payload.get("rankings", [])[: args.top]]
    if not tickers:
        parser.error("predict JSON에 분석할 rankings가 없습니다.")
    if args.lookback_days <= 0 or args.min_observations < 2:
        parser.error("lookback-days는 양수, min-observations는 2 이상이어야 합니다.")

    snapshot = build_risk_snapshot(
        tickers,
        analysis_date,
        lookback_days=args.lookback_days,
        min_observations=args.min_observations,
    )
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"risk snapshot 저장: {output_path} ({len(snapshot['annualized_volatility'])}개 종목)")


if __name__ == "__main__":
    main()
