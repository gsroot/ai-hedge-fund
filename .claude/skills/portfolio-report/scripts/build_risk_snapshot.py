#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd


SCRIPT_DIR = Path(__file__).resolve().parent
PREDICT_SCRIPTS = Path(__file__).resolve().parents[2] / "predict" / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
if str(PREDICT_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(PREDICT_SCRIPTS))

from data_fetcher import get_prices  # noqa: E402
from market_regime import assess_market_regime  # noqa: E402
from ticker_utils import is_korean_ticker  # noqa: E402


DEFAULT_MAX_PRICE_AGE_DAYS = 7  # Calendar days; configurable to accommodate long exchange holidays.
MAX_INTERVAL_DAYS = 7


INDEX_BENCHMARKS = {
    "sp500": "SPY",
    "nasdaq100": "QQQ",
    "kospi": "^KS11",
    "kospi200": "^KS11",
    "kosdaq": "^KQ11",
    "kosdaq150": "^KQ11",
    "krx": "^KS11",
}


def benchmark_for_index(index_name: str | None) -> str:
    return INDEX_BENCHMARKS.get((index_name or "sp500").lower(), "SPY")


def _price_row_date(row: dict) -> object | None:
    """Normalize US (`date`) and Korean (`time`) price row schemas."""
    return row.get("date") or row.get("time")


def _bounded_closes(rows, analysis_date, start_date=None):
    cutoff = pd.Timestamp(analysis_date).date()
    start = pd.Timestamp(start_date).date() if start_date else None
    values = {}
    for row in rows:
        day = _price_row_date(row)
        value = row.get("close")
        if day is None or value is None:
            continue
        stamp = pd.Timestamp(day)
        if pd.isna(stamp) or stamp.date() > cutoff or (start and stamp.date() < start):
            continue
        close = float(value)
        if not math.isfinite(close) or close <= 0:
            continue
        date = pd.Timestamp(stamp.date())
        if date in values and values[date] != close:
            raise ValueError("conflicting prices for one date")
        values[date] = close
    series = pd.Series(values, dtype=float).sort_index()
    series.index = pd.DatetimeIndex(series.index)
    return series


def _fetch_series(ticker, start_date, analysis_date):
    try:
        rows = get_prices(ticker, start_date, analysis_date)
        prices = _bounded_closes(rows, analysis_date, start_date)
        return prices, "available" if len(prices) else "empty"
    except Exception as exc:
        return pd.Series(dtype=float, index=pd.DatetimeIndex([])), f"provider_error:{type(exc).__name__}"


def _history(prices, ticker, analysis_date, max_age):
    age = (pd.Timestamp(analysis_date) - prices.index[-1]).days
    relatives = prices / prices.iloc[0]
    return {
        "provider_route": "korean_FDR_or_PyKRX_cache" if is_korean_ticker(ticker) else "Yahoo_Finance_or_cache",
        "price_basis": "provider_close_adjustment_unverified",
        "first_date": str(prices.index[0].date()), "last_date": str(prices.index[-1].date()),
        "observations": len(prices), "age_days": age, "freshness": "recent" if age <= max_age else "stale",
        "relative_closes": {str(date.date()): float(value) for date, value in relatives.items()},
    }


def _interval_returns(prices, max_interval_days):
    # Correlate only observations with the same start AND end, including market holidays.
    change = prices.pct_change(fill_method=None).iloc[1:]
    starts, ends = prices.index[:-1], prices.index[1:]
    change.index = pd.MultiIndex.from_arrays([starts, ends], names=["start", "end"])
    return change[(ends - starts).days <= max_interval_days]


def _fx_pair(value):
    pair = value.strip().upper()
    if not re.fullmatch("[A-Z]{3}/[A-Z]{3}", pair) or pair[:3] == pair[4:]:
        raise ValueError("FX pair must use two distinct currencies, for example USD/KRW")
    return pair


def build_risk_snapshot(
    tickers: list[str],
    analysis_date: str,
    lookback_days: int = 400,
    min_observations: int = 60,
    benchmark: str = "SPY",
    max_price_age_days: int = DEFAULT_MAX_PRICE_AGE_DAYS,
    fx_pairs: tuple[str, ...] | list[str] = (),
    max_interval_days: int = MAX_INTERVAL_DAYS,
) -> dict:
    if lookback_days <= 0 or min_observations < 2 or max_price_age_days < 0 or max_interval_days < 1:
        raise ValueError("invalid risk lookback, minimum observations or price age")
    pairs = list(dict.fromkeys(_fx_pair(pair) for pair in fx_pairs))
    end_dt = datetime.strptime(analysis_date, "%Y-%m-%d")
    start_date = (end_dt - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
    series = {}
    history = {}
    dropped = {}
    valid = {}
    for ticker in dict.fromkeys([*tickers, benchmark]):
        prices, status = _fetch_series(ticker, start_date, analysis_date)
        series[ticker] = prices
        if prices.empty:
            dropped[ticker] = status
            continue
        history[ticker] = _history(prices, ticker, analysis_date, max_price_age_days)
        if ticker in tickers:
            intervals = _interval_returns(prices, max_interval_days)
            if history[ticker]["freshness"] == "stale":
                dropped[ticker] = "stale_price_history"
            elif len(intervals) < min_observations:
                dropped[ticker] = f"insufficient_returns:{len(intervals)}"
            elif prices.index.to_series().diff().dt.days.median() > 2:
                dropped[ticker] = "daily_frequency_unverified"
            else:
                valid[ticker] = intervals

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
    present = returns.notna().astype(int)
    counts = present.T.dot(present)
    benchmark_closes = series[benchmark]
    benchmark_status = history.get(benchmark, {}).get("freshness", dropped.get(benchmark))
    if benchmark_status == "recent" and len(benchmark_closes) > 1:
        day_gaps = benchmark_closes.tail(252).index.to_series().diff().dt.days
        if day_gaps.max() > max_interval_days or day_gaps.median() > 2:
            benchmark_status = "sparse_price_history"
    if benchmark_status != "recent":
        benchmark_closes = benchmark_closes.iloc[:0]
    market_regime = assess_market_regime(
        benchmark_closes,
        benchmark=benchmark,
        as_of_date=analysis_date,
    )
    market_regime["cash_weight_interpretation"] = (
        "legacy_insufficient_data_policy_prior" if market_regime["data_quality"] == "insufficient" else "legacy_rule_reference"
    )
    fx_history = {}
    for pair in pairs:
        symbol = pair.replace("/", "") + "=X"
        fx_prices, status = _fetch_series(symbol, start_date, analysis_date)
        fx_history[pair] = {"symbol": symbol, "direction": "base_per_foreign", "status": status}
        if len(fx_prices):
            fx_history[pair].update(_history(fx_prices, symbol, analysis_date, max_price_age_days))
    recent_tickers = [ticker for ticker in valid if history[ticker]["freshness"] == "recent"]
    coverage = "unavailable"
    if recent_tickers:
        coverage = "available" if len(recent_tickers) == len(set(tickers)) else "partial"
    return {
        "schema_version": "portfolio_risk_v2",
        "available_at": datetime.now(timezone.utc).isoformat(),
        "analysis_date": analysis_date,
        "lookback_start": start_date,
        "min_observations": min_observations,
        "max_price_age_days": max_price_age_days,
        "max_interval_days": max_interval_days,
        "price_history": history,
        "price_coverage_status": coverage,
        "fx_history": fx_history,
        "pairwise_observations": counts.to_dict(),
        "benchmark_price_status": benchmark_status,
        "annualized_volatility": annualized_volatility,
        "correlation": correlation,
        "market_regime": market_regime,
        "dropped": dropped,
    }


def risk_tickers(payload, top, extra_tickers):
    if top is None and isinstance(payload.get("research_shortlist"), dict):
        candidates = payload["research_shortlist"]["candidates"]
    else:
        candidates = payload.get("rankings", [])[:30 if top is None else top]
    extras = [ticker.strip().upper() for ticker in extra_tickers.split(",") if ticker.strip()]
    return list(dict.fromkeys([item["ticker"] for item in candidates] + extras))


def main() -> None:
    parser = argparse.ArgumentParser(description="predict 후보의 point-in-time 변동성·상관 스냅샷 생성")
    parser.add_argument("--predict-json", required=True)
    parser.add_argument("--top", type=int, help="상위 N위로 제한. 기본은 predict 조사 후보군, 기존 파일은 상위 30개")
    parser.add_argument("--lookback-days", type=int, default=400)
    parser.add_argument("--min-observations", type=int, default=60)
    parser.add_argument("--benchmark", help="시장 국면 벤치마크. 생략 시 predict 인덱스에 따라 선택")
    parser.add_argument("--extra-tickers", default="", help="독립 분석할 ETF 등 추가 대상, 콤마 구분")
    parser.add_argument("--fx-pair", action="append", default=[], help="외화/기준통화. USD/KRW는 1 USD당 KRW, 여러 번 지정 가능")
    parser.add_argument("--max-price-age-days", type=int, default=DEFAULT_MAX_PRICE_AGE_DAYS)
    parser.add_argument("--max-interval-days", type=int, default=MAX_INTERVAL_DAYS,
                        help="연속 관측일 사이에 허용할 최대 달력 일수. 긴 거래소 휴장 시 조정")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    payload = json.loads(Path(args.predict_json).read_text(encoding="utf-8"))
    analysis_date = payload.get("analysis_date")
    if not analysis_date:
        parser.error("predict JSON에 analysis_date가 없습니다.")
    if args.top is not None and args.top <= 0:
        parser.error("--top은 양수여야 합니다.")
    tickers = risk_tickers(payload, args.top, args.extra_tickers)
    if not tickers:
        parser.error("predict JSON에 분석할 rankings가 없습니다.")
    if args.lookback_days <= 0 or args.min_observations < 2:
        parser.error("lookback-days는 양수, min-observations는 2 이상이어야 합니다.")

    try:
        snapshot = build_risk_snapshot(
            tickers, analysis_date, lookback_days=args.lookback_days, min_observations=args.min_observations,
            benchmark=args.benchmark or benchmark_for_index(payload.get("index")),
            fx_pairs=args.fx_pair, max_price_age_days=args.max_price_age_days, max_interval_days=args.max_interval_days,
        )
    except ValueError as exc:
        parser.error(str(exc))
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False, allow_nan=False), encoding="utf-8")
    regime = snapshot["market_regime"]
    print(
        f"risk snapshot 저장: {output_path} "
        f"({len(snapshot['annualized_volatility'])}개 종목, "
        f"가격 관측={snapshot['price_coverage_status']}, 시장={regime['regime']})"
    )


if __name__ == "__main__":
    main()
