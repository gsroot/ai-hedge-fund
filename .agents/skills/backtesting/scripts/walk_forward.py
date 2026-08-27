#!/usr/bin/env python3
"""Cost-aware walk-forward validation on historical Dow membership and real OHLC.

Only timestamped market prices and membership effective dates are used for signals.
Fundamentals, news, current market-cap rankings, and current index membership are
deliberately excluded because they are not available as point-in-time vintages in
the default project environment.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd
import yfinance as yf


UNIVERSE_SOURCE = (
    "https://en.wikipedia.org/wiki/"
    "Historical_components_of_the_Dow_Jones_Industrial_Average"
)
PRICE_SOURCE = "Yahoo Finance via yfinance"

# Snapshot immediately after the 2013-09-23 change. RTX represents the continuous
# Yahoo history of United Technologies/RTX; DD represents DuPont/DowDuPont until
# Dow Inc. replaced it in 2019. These aliases are disclosed in every result.
INITIAL_DOW_MEMBERS = {
    "MMM", "AXP", "T", "BA", "CAT", "CVX", "CSCO", "KO", "DD", "XOM",
    "GE", "GS", "HD", "INTC", "IBM", "JNJ", "JPM", "MCD", "MRK", "MSFT",
    "NKE", "PFE", "PG", "TRV", "UNH", "RTX", "VZ", "V", "WMT", "DIS",
}

# Effective-date replacements after the initial snapshot. Corporate ticker/name
# continuities that do not change the data key are recorded separately below.
DOW_CHANGES = (
    ("2015-03-19", {"AAPL"}, {"T"}),
    ("2017-09-01", set(), set()),  # E.I. du Pont -> DowDuPont, represented by DD
    ("2018-06-26", {"WBA"}, {"GE"}),
    ("2019-04-02", {"DOW"}, {"DD"}),
    ("2020-04-06", set(), set()),  # United Technologies -> RTX continuity
    ("2020-08-31", {"AMGN", "HON", "CRM"}, {"XOM", "PFE", "RTX"}),
    ("2024-02-26", {"AMZN"}, {"WBA"}),
    ("2024-11-08", {"NVDA", "SHW"}, {"INTC", "DOW"}),
    ("2026-06-29", {"GOOGL"}, {"VZ"}),
)

UNIVERSE_ALIASES = {
    "DD": "E.I. du Pont and DowDuPont continuous Yahoo series before 2019-04-02",
    "RTX": "United Technologies and RTX continuous Yahoo series before 2020-08-31",
}


@dataclass(frozen=True)
class StrategyParams:
    lookback_days: int
    skip_recent_days: int
    top_n: int


DEFAULT_PARAMETER_GRID = tuple(
    StrategyParams(lookback, skip, top_n)
    for lookback in (63, 126, 252)
    for skip in (0, 21)
    for top_n in (5, 10)
)


def dow_members_as_of(date: str | pd.Timestamp) -> set[str]:
    """Return the membership set effective on a historical date."""
    as_of = pd.Timestamp(date).normalize()
    if as_of < pd.Timestamp("2013-09-23"):
        raise ValueError("Dow membership history is only defined from 2013-09-23.")
    members = set(INITIAL_DOW_MEMBERS)
    for effective_date, added, removed in DOW_CHANGES:
        if as_of >= pd.Timestamp(effective_date):
            members.difference_update(removed)
            members.update(added)
    if len(members) != 30:
        raise AssertionError(f"Dow membership must contain 30 names, got {len(members)}")
    return members


def all_required_tickers(end_date: str | pd.Timestamp) -> list[str]:
    tickers = set(INITIAL_DOW_MEMBERS)
    for effective_date, added, _ in DOW_CHANGES:
        if pd.Timestamp(effective_date) <= pd.Timestamp(end_date):
            tickers.update(added)
    tickers.add("DIA")
    return sorted(tickers)


def _field_frame(raw: pd.DataFrame, field: str, batch: list[str]) -> pd.DataFrame:
    if raw.empty or field not in raw:
        return pd.DataFrame(index=raw.index)
    values = raw[field]
    if isinstance(values, pd.Series):
        name = batch[0] if len(batch) == 1 else str(values.name)
        values = values.to_frame(name=name)
    values.columns = [str(column).upper() for column in values.columns]
    return values


def download_adjusted_ohlc(
    tickers: Iterable[str], start_date: str, end_date: str
) -> tuple[pd.DataFrame, pd.DataFrame, list[str]]:
    """Download raw OHLC and convert Open to the Adj Close scale."""
    requested = sorted(set(ticker.upper() for ticker in tickers))
    end_exclusive = (pd.Timestamp(end_date) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    adjusted_open: dict[str, pd.Series] = {}
    adjusted_close: dict[str, pd.Series] = {}
    failed: list[str] = []

    for offset in range(0, len(requested), 20):
        batch = requested[offset : offset + 20]
        raw = yf.download(
            batch,
            start=start_date,
            end=end_exclusive,
            auto_adjust=False,
            actions=False,
            progress=False,
            threads=True,
            group_by="column",
        )
        opens = _field_frame(raw, "Open", batch)
        closes = _field_frame(raw, "Close", batch)
        adj_closes = _field_frame(raw, "Adj Close", batch)
        for ticker in batch:
            if ticker not in closes or ticker not in adj_closes:
                failed.append(ticker)
                continue
            close = pd.to_numeric(closes[ticker], errors="coerce")
            adj_close = pd.to_numeric(adj_closes[ticker], errors="coerce")
            open_series = pd.to_numeric(opens.get(ticker), errors="coerce")
            factor = adj_close / close.replace(0, np.nan)
            adj_open = open_series * factor
            if adj_close.dropna().empty or adj_open.dropna().empty:
                failed.append(ticker)
                continue
            adjusted_open[ticker] = adj_open
            adjusted_close[ticker] = adj_close

    open_frame = pd.DataFrame(adjusted_open).sort_index()
    close_frame = pd.DataFrame(adjusted_close).sort_index()
    index = open_frame.index.union(close_frame.index)
    open_frame = open_frame.reindex(index)
    close_frame = close_frame.reindex(index)
    index = pd.DatetimeIndex(index).tz_localize(None).normalize()
    open_frame.index = index
    close_frame.index = index
    return open_frame, close_frame, sorted(set(failed))


def save_price_cache(path: Path, opens: pd.DataFrame, closes: pd.DataFrame) -> str:
    records = []
    for ticker in sorted(set(opens.columns).union(closes.columns)):
        index = opens.index.union(closes.index)
        open_series = (
            opens[ticker].reindex(index)
            if ticker in opens
            else pd.Series(index=index, dtype=float)
        )
        close_series = (
            closes[ticker].reindex(index)
            if ticker in closes
            else pd.Series(index=index, dtype=float)
        )
        frame = pd.DataFrame(
            {
                "date": index,
                "ticker": ticker,
                "open": open_series,
                "close": close_series,
            }
        ).dropna(subset=["open", "close"], how="all")
        records.append(frame)
    combined = pd.concat(records, ignore_index=True) if records else pd.DataFrame()
    path.parent.mkdir(parents=True, exist_ok=True)
    combined.to_csv(path, index=False, date_format="%Y-%m-%d")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_price_cache(path: Path) -> tuple[pd.DataFrame, pd.DataFrame, str]:
    data = pd.read_csv(path, parse_dates=["date"])
    opens = data.pivot(index="date", columns="ticker", values="open").sort_index()
    closes = data.pivot(index="date", columns="ticker", values="close").sort_index()
    return opens, closes, hashlib.sha256(path.read_bytes()).hexdigest()


def month_open_dates(calendar: pd.DatetimeIndex) -> set[pd.Timestamp]:
    values = pd.Series(calendar, index=calendar)
    return set(values.groupby(calendar.to_period("M")).first())


def momentum_value(
    close: pd.Series,
    signal_date: pd.Timestamp,
    params: StrategyParams,
) -> float | None:
    history = close.loc[:signal_date].dropna()
    end_position = len(history) - 1 - params.skip_recent_days
    start_position = end_position - params.lookback_days
    if start_position < 0 or end_position < 0:
        return None
    start_value = float(history.iloc[start_position])
    end_value = float(history.iloc[end_position])
    if start_value <= 0 or end_value <= 0:
        return None
    return end_value / start_value - 1.0


def _valid_price(frame: pd.DataFrame, date: pd.Timestamp, ticker: str) -> float | None:
    if ticker not in frame or date not in frame.index:
        return None
    value = frame.at[date, ticker]
    if pd.isna(value) or float(value) <= 0:
        return None
    return float(value)


def target_weights_for_date(
    opens: pd.DataFrame,
    closes: pd.DataFrame,
    signal_date: pd.Timestamp,
    execution_date: pd.Timestamp,
    params: StrategyParams,
    min_universe_coverage: float,
) -> tuple[dict[str, float], dict]:
    members = sorted(dow_members_as_of(signal_date))
    scores: dict[str, float] = {}
    for ticker in members:
        if ticker not in closes or _valid_price(opens, execution_date, ticker) is None:
            continue
        value = momentum_value(closes[ticker], signal_date, params)
        if value is not None:
            scores[ticker] = value
    coverage = len(scores) / len(members)
    selected: list[tuple[str, float]] = []
    if coverage >= min_universe_coverage:
        selected = [
            item for item in sorted(scores.items(), key=lambda item: (-item[1], item[0]))
            if item[1] > 0
        ][: params.top_n]
    # Keep the name cap implied by top_n even when fewer names pass the positive
    # momentum filter. Unused capacity remains cash.
    weights = {ticker: 1.0 / params.top_n for ticker, _ in selected}
    detail = {
        "signal_date": signal_date.strftime("%Y-%m-%d"),
        "execution_date": execution_date.strftime("%Y-%m-%d"),
        "expected_members": len(members),
        "eligible_members": len(scores),
        "missing_members": sorted(set(members) - set(scores)),
        "coverage": coverage,
        "selected": [ticker for ticker, _ in selected],
        "selected_momentum": {ticker: value for ticker, value in selected},
        "target_invested_weight": sum(weights.values()),
        "parameters": asdict(params),
        "coverage_gate_passed": coverage >= min_universe_coverage,
    }
    return weights, detail


def _params_for_date(
    date: pd.Timestamp,
    fixed_params: StrategyParams | None,
    schedule: list[dict] | None,
) -> StrategyParams:
    if fixed_params is not None:
        return fixed_params
    for item in schedule or []:
        if pd.Timestamp(item["start"]) <= date <= pd.Timestamp(item["end"]):
            return item["params"]
    raise ValueError(f"No parameter schedule covers {date:%Y-%m-%d}")


def build_momentum_weight_schedule(
    opens: pd.DataFrame,
    closes: pd.DataFrame,
    start_date: str,
    end_date: str,
    min_universe_coverage: float,
    fixed_params: StrategyParams | None = None,
    schedule: list[dict] | None = None,
) -> dict[pd.Timestamp, dict]:
    calendar = pd.DatetimeIndex(closes.index).sort_values()
    if "DIA" in closes:
        calendar = calendar[closes["DIA"].notna().reindex(calendar, fill_value=False)]
    dates = calendar[
        (calendar >= pd.Timestamp(start_date)) & (calendar <= pd.Timestamp(end_date))
    ]
    if dates.empty:
        raise ValueError(f"No trading dates between {start_date} and {end_date}")
    rebalance_dates = month_open_dates(dates)
    weights_by_date = {}
    for date in rebalance_dates:
        earlier_dates = calendar[calendar < date]
        if len(earlier_dates) == 0:
            continue
        signal_date = earlier_dates[-1]
        params = _params_for_date(date, fixed_params, schedule)
        target_weights, detail = target_weights_for_date(
            opens,
            closes,
            signal_date,
            date,
            params,
            min_universe_coverage,
        )
        weights_by_date[date] = {"weights": target_weights, "detail": detail}
    return weights_by_date


def simulate_weight_schedule(
    opens: pd.DataFrame,
    closes: pd.DataFrame,
    start_date: str,
    end_date: str,
    cost_rate: float,
    weights_by_date: dict[pd.Timestamp, dict],
) -> dict:
    """Execute precomputed point-in-time target weights at each exact market open."""
    calendar = pd.DatetimeIndex(closes.index).sort_values()
    if "DIA" in closes:
        calendar = calendar[closes["DIA"].notna().reindex(calendar, fill_value=False)]
    dates = calendar[
        (calendar >= pd.Timestamp(start_date)) & (calendar <= pd.Timestamp(end_date))
    ]
    if dates.empty:
        raise ValueError(f"No trading dates between {start_date} and {end_date}")
    shares: dict[str, float] = {}
    cash = 1.0
    previous_value = 1.0
    last_close: dict[str, float] = {}
    equity_values: list[float] = []
    daily_returns: list[float] = []
    rebalance_log: list[dict] = []
    total_cost = 0.0
    total_turnover = 0.0

    for date in dates:
        open_marks: dict[str, float] = {}
        for ticker in shares:
            value = _valid_price(opens, date, ticker) or last_close.get(ticker)
            if value is None:
                raise ValueError(f"Missing valuation price for held ticker {ticker} on {date}")
            open_marks[ticker] = value
        value_at_open = cash + sum(shares[ticker] * open_marks[ticker] for ticker in shares)

        if date in weights_by_date:
            target_weights = weights_by_date[date]["weights"]
            detail = dict(weights_by_date[date]["detail"])
            trade_tickers = set(shares).union(target_weights)
            prices = {}
            for ticker in trade_tickers:
                price = _valid_price(opens, date, ticker)
                if price is None:
                    raise ValueError(
                        f"Cannot rebalance {ticker} without an exact open on {date:%Y-%m-%d}"
                    )
                prices[ticker] = price

            investable_value = value_at_open
            target_shares: dict[str, float] = {}
            transaction_cost = 0.0
            turnover_notional = 0.0
            for _ in range(8):
                target_shares = {
                    ticker: investable_value * weight / prices[ticker]
                    for ticker, weight in target_weights.items()
                }
                turnover_notional = sum(
                    abs(target_shares.get(ticker, 0.0) - shares.get(ticker, 0.0))
                    * prices[ticker]
                    for ticker in trade_tickers
                )
                transaction_cost = turnover_notional * cost_rate
                revised_value = max(0.0, value_at_open - transaction_cost)
                if abs(revised_value - investable_value) < 1e-12:
                    break
                investable_value = revised_value

            cash = (
                value_at_open
                - sum(target_shares[ticker] * prices[ticker] for ticker in target_shares)
                - transaction_cost
            )
            shares = {
                ticker: quantity
                for ticker, quantity in target_shares.items()
                if quantity > 1e-15
            }
            turnover_ratio = turnover_notional / value_at_open if value_at_open else 0.0
            total_cost += transaction_cost
            total_turnover += turnover_ratio
            detail.update(
                {
                    "turnover": turnover_ratio,
                    "transaction_cost": transaction_cost,
                    "portfolio_value_before_trade": value_at_open,
                }
            )
            rebalance_log.append(detail)

        close_marks: dict[str, float] = {}
        for ticker in shares:
            value = _valid_price(closes, date, ticker)
            if value is None:
                value = _valid_price(opens, date, ticker) or last_close.get(ticker)
            if value is None:
                raise ValueError(f"Missing close for held ticker {ticker} on {date}")
            close_marks[ticker] = value
            last_close[ticker] = value
        portfolio_value = cash + sum(
            shares[ticker] * close_marks[ticker] for ticker in shares
        )
        equity_values.append(portfolio_value)
        daily_returns.append(portfolio_value / previous_value - 1.0)
        previous_value = portfolio_value

    equity = pd.Series(equity_values, index=dates, name="strategy")
    returns = pd.Series(daily_returns, index=dates, name="strategy_return")
    return {
        "equity": equity,
        "returns": returns,
        "rebalances": rebalance_log,
        "total_transaction_cost": total_cost,
        "total_turnover": total_turnover,
    }


def simulate_strategy(
    opens: pd.DataFrame,
    closes: pd.DataFrame,
    start_date: str,
    end_date: str,
    cost_rate: float,
    min_universe_coverage: float,
    fixed_params: StrategyParams | None = None,
    schedule: list[dict] | None = None,
) -> dict:
    weights_by_date = build_momentum_weight_schedule(
        opens,
        closes,
        start_date,
        end_date,
        min_universe_coverage,
        fixed_params=fixed_params,
        schedule=schedule,
    )
    return simulate_weight_schedule(
        opens,
        closes,
        start_date,
        end_date,
        cost_rate,
        weights_by_date,
    )


def simulate_benchmark(
    opens: pd.DataFrame,
    closes: pd.DataFrame,
    start_date: str,
    end_date: str,
    cost_rate: float,
) -> dict:
    dates = pd.DatetimeIndex(closes.index)
    dates = dates[
        (dates >= pd.Timestamp(start_date))
        & (dates <= pd.Timestamp(end_date))
        & closes["DIA"].notna().reindex(dates, fill_value=False)
    ]
    first_date = dates[0]
    first_open = _valid_price(opens, first_date, "DIA")
    if first_open is None:
        raise ValueError("DIA has no opening price on the first OOS date")
    shares = (1.0 - cost_rate) / first_open
    equity = (closes.loc[dates, "DIA"] * shares).rename("benchmark")
    returns = equity.pct_change()
    returns.iloc[0] = equity.iloc[0] - 1.0
    return {"equity": equity, "returns": returns, "entry_cost": cost_rate}


def performance_metrics(equity: pd.Series, returns: pd.Series) -> dict:
    clean_returns = returns.replace([np.inf, -np.inf], np.nan).dropna()
    if equity.empty or clean_returns.empty:
        raise ValueError("Cannot calculate performance metrics from empty data")
    total_return = float(equity.iloc[-1] - 1.0)
    years = max(len(clean_returns) / 252.0, 1.0 / 252.0)
    cagr = float(equity.iloc[-1] ** (1.0 / years) - 1.0)
    volatility = float(clean_returns.std(ddof=1) * math.sqrt(252))
    sharpe = (
        float(clean_returns.mean() / clean_returns.std(ddof=1) * math.sqrt(252))
        if clean_returns.std(ddof=1) > 0
        else 0.0
    )
    downside = clean_returns[clean_returns < 0]
    sortino = (
        float(clean_returns.mean() / downside.std(ddof=1) * math.sqrt(252))
        if len(downside) > 1 and downside.std(ddof=1) > 0
        else 0.0
    )
    drawdown = equity / equity.cummax() - 1.0
    max_drawdown = float(drawdown.min())
    calmar = cagr / abs(max_drawdown) if max_drawdown < 0 else 0.0
    annual_returns = {
        str(year): float((1.0 + group).prod() - 1.0)
        for year, group in clean_returns.groupby(clean_returns.index.year)
    }
    monthly = (1.0 + clean_returns).groupby(
        [clean_returns.index.year, clean_returns.index.month]
    ).prod() - 1.0
    return {
        "total_return": total_return,
        "cagr": cagr,
        "annualized_volatility": volatility,
        "sharpe_ratio": sharpe,
        "sortino_ratio": sortino,
        "max_drawdown": max_drawdown,
        "calmar_ratio": calmar,
        "positive_month_rate": float((monthly > 0).mean()) if len(monthly) else 0.0,
        "annual_returns": annual_returns,
        "positive_years": int(sum(value > 0 for value in annual_returns.values())),
        "years_observed": len(annual_returns),
    }


def block_bootstrap_cagr(
    returns: pd.Series,
    samples: int = 1000,
    block_size: int = 21,
    seed: int = 20260826,
) -> dict:
    values = returns.dropna().to_numpy(dtype=float)
    if len(values) < block_size:
        return {"low": None, "median": None, "high": None}
    rng = np.random.default_rng(seed)
    estimates = []
    block_count = math.ceil(len(values) / block_size)
    max_start = len(values) - block_size
    for _ in range(samples):
        starts = rng.integers(0, max_start + 1, size=block_count)
        sample = np.concatenate(
            [values[start : start + block_size] for start in starts]
        )[: len(values)]
        ending_value = float(np.prod(1.0 + sample))
        estimates.append(ending_value ** (252.0 / len(sample)) - 1.0)
    low, median, high = np.quantile(estimates, [0.025, 0.5, 0.975])
    return {"low": float(low), "median": float(median), "high": float(high)}


def paired_block_bootstrap_cagr_difference(
    strategy_returns: pd.Series,
    benchmark_returns: pd.Series,
    samples: int = 1000,
    block_size: int = 21,
    seed: int = 20260826,
) -> dict:
    """Bootstrap paired return blocks and estimate annualized CAGR difference.

    Sampling the two series with identical block locations preserves their market
    co-movement. This is more informative than comparing two independent CAGR
    intervals when deciding whether an apparent edge survived out of sample.
    """
    paired = pd.concat(
        [strategy_returns.rename("strategy"), benchmark_returns.rename("benchmark")],
        axis=1,
    ).dropna()
    if len(paired) < block_size:
        return {
            "low": None,
            "median": None,
            "high": None,
            "probability_greater_than_zero": None,
        }
    values = paired.to_numpy(dtype=float)
    rng = np.random.default_rng(seed)
    estimates = []
    block_count = math.ceil(len(values) / block_size)
    max_start = len(values) - block_size
    for _ in range(samples):
        starts = rng.integers(0, max_start + 1, size=block_count)
        sample = np.concatenate(
            [values[start : start + block_size] for start in starts]
        )[: len(values)]
        strategy_end = float(np.prod(1.0 + sample[:, 0]))
        benchmark_end = float(np.prod(1.0 + sample[:, 1]))
        annualizer = 252.0 / len(sample)
        estimates.append(
            strategy_end**annualizer - benchmark_end**annualizer
        )
    low, median, high = np.quantile(estimates, [0.025, 0.5, 0.975])
    return {
        "low": float(low),
        "median": float(median),
        "high": float(high),
        "probability_greater_than_zero": float(np.mean(np.asarray(estimates) > 0)),
    }


def make_folds(start_oos: str, end_oos: str, train_years: int) -> list[dict]:
    start = pd.Timestamp(start_oos)
    end = pd.Timestamp(end_oos)
    folds = []
    for year in range(start.year, end.year + 1):
        test_start = max(start, pd.Timestamp(year=year, month=1, day=1))
        test_end = min(end, pd.Timestamp(year=year, month=12, day=31))
        train_end = test_start - pd.Timedelta(days=1)
        train_start = test_start - pd.DateOffset(years=train_years)
        folds.append(
            {
                "train_start": train_start.strftime("%Y-%m-%d"),
                "train_end": train_end.strftime("%Y-%m-%d"),
                "test_start": test_start.strftime("%Y-%m-%d"),
                "test_end": test_end.strftime("%Y-%m-%d"),
            }
        )
    return folds


def select_fold_parameters(
    opens: pd.DataFrame,
    closes: pd.DataFrame,
    fold: dict,
    parameter_grid: Iterable[StrategyParams],
    cost_rate: float,
    min_universe_coverage: float,
) -> tuple[StrategyParams, dict, list[dict]]:
    trials = []
    for params in parameter_grid:
        simulation = simulate_strategy(
            opens,
            closes,
            fold["train_start"],
            fold["train_end"],
            cost_rate,
            min_universe_coverage,
            fixed_params=params,
        )
        metrics = performance_metrics(simulation["equity"], simulation["returns"])
        trials.append(
            {
                "params": params,
                "metrics": metrics,
                "turnover": simulation["total_turnover"],
                "transaction_cost": simulation["total_transaction_cost"],
            }
        )
    best = max(
        trials,
        key=lambda trial: (
            trial["metrics"]["sharpe_ratio"],
            trial["metrics"]["cagr"],
            trial["metrics"]["max_drawdown"],
            -trial["turnover"],
            -trial["params"].lookback_days,
            -trial["params"].top_n,
        ),
    )
    serializable_trials = [
        {
            "parameters": asdict(trial["params"]),
            "metrics": trial["metrics"],
            "turnover": trial["turnover"],
            "transaction_cost": trial["transaction_cost"],
        }
        for trial in trials
    ]
    return best["params"], best["metrics"], serializable_trials


def run_cost_sensitivity(
    opens: pd.DataFrame,
    closes: pd.DataFrame,
    folds: list[dict],
    total_cost_bps_values: Iterable[float],
    min_universe_coverage: float,
) -> dict[str, dict]:
    """Repeat training-only parameter selection under alternative cost assumptions."""
    results = {}
    for total_cost_bps in total_cost_bps_values:
        cost_rate = total_cost_bps / 10000.0
        schedule = []
        selected_parameters = []
        for fold in folds:
            params, _, _ = select_fold_parameters(
                opens,
                closes,
                fold,
                DEFAULT_PARAMETER_GRID,
                cost_rate,
                min_universe_coverage,
            )
            schedule.append(
                {"start": fold["test_start"], "end": fold["test_end"], "params": params}
            )
            selected_parameters.append(
                {"test_year": fold["test_start"][:4], **asdict(params)}
            )
        simulation = simulate_strategy(
            opens,
            closes,
            folds[0]["test_start"],
            folds[-1]["test_end"],
            cost_rate,
            min_universe_coverage,
            schedule=schedule,
        )
        results[f"{total_cost_bps:g}"] = {
            "total_cost_bps_each_rebalance_leg": total_cost_bps,
            "metrics": performance_metrics(simulation["equity"], simulation["returns"]),
            "transaction_cost_fraction_of_initial_capital": simulation[
                "total_transaction_cost"
            ],
            "selected_parameters": selected_parameters,
        }
    return results


def fixed_grid_diagnostics(
    opens: pd.DataFrame,
    closes: pd.DataFrame,
    start_date: str,
    end_date: str,
    cost_rate: float,
    min_universe_coverage: float,
) -> list[dict]:
    """Evaluate fixed configurations on OOS for stability diagnostics, never selection."""
    rows = []
    for params in DEFAULT_PARAMETER_GRID:
        simulation = simulate_strategy(
            opens,
            closes,
            start_date,
            end_date,
            cost_rate,
            min_universe_coverage,
            fixed_params=params,
        )
        rows.append(
            {
                "parameters": asdict(params),
                "metrics": performance_metrics(simulation["equity"], simulation["returns"]),
            }
        )
    return rows


def _json_default(value):
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, pd.Timestamp):
        return value.strftime("%Y-%m-%d")
    raise TypeError(f"Cannot serialize {type(value)!r}")


def run_walk_forward(args: argparse.Namespace) -> dict:
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    cache_path = output_dir / "adjusted_ohlc.csv"
    cache_manifest_path = output_dir / "price_cache_manifest.json"
    folds = make_folds(args.start_oos, args.end_oos, args.train_years)
    earliest_train = pd.Timestamp(folds[0]["train_start"])
    download_start = (earliest_train - pd.Timedelta(days=450)).strftime("%Y-%m-%d")
    requested_tickers = all_required_tickers(args.end_oos)
    downloaded_at = datetime.now(timezone.utc).isoformat()

    if cache_path.exists() and not args.refresh_data:
        opens, closes, cache_hash = load_price_cache(cache_path)
        if cache_manifest_path.exists():
            cache_manifest = json.loads(cache_manifest_path.read_text(encoding="utf-8"))
            downloaded_at = cache_manifest.get("downloaded_at_utc", downloaded_at)
        else:
            downloaded_at = datetime.fromtimestamp(
                cache_path.stat().st_mtime, tz=timezone.utc
            ).isoformat()
        failed_tickers = sorted(set(requested_tickers) - set(closes.columns))
        data_mode = "cache"
    else:
        opens, closes, failed_tickers = download_adjusted_ohlc(
            requested_tickers, download_start, args.end_oos
        )
        cache_hash = save_price_cache(cache_path, opens, closes)
        data_mode = "download"
        cache_manifest_path.write_text(
            json.dumps(
                {
                    "downloaded_at_utc": downloaded_at,
                    "source": PRICE_SOURCE,
                    "start": download_start,
                    "end": args.end_oos,
                    "requested_tickers": requested_tickers,
                    "failed_tickers": failed_tickers,
                    "sha256": cache_hash,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    if "DIA" not in opens or "DIA" not in closes:
        raise ValueError("DIA benchmark data is required but unavailable")

    cost_rate = (args.commission_bps + args.slippage_bps) / 10000.0
    selected_folds = []
    schedule = []
    for fold in folds:
        params, train_metrics, trials = select_fold_parameters(
            opens,
            closes,
            fold,
            DEFAULT_PARAMETER_GRID,
            cost_rate,
            args.min_universe_coverage,
        )
        independent_test = simulate_strategy(
            opens,
            closes,
            fold["test_start"],
            fold["test_end"],
            cost_rate,
            args.min_universe_coverage,
            fixed_params=params,
        )
        test_metrics = performance_metrics(
            independent_test["equity"], independent_test["returns"]
        )
        selected_folds.append(
            {
                **fold,
                "selected_parameters": asdict(params),
                "training_metrics": train_metrics,
                "test_metrics_reset_at_fold_start": test_metrics,
                "training_grid": trials,
            }
        )
        schedule.append(
            {"start": fold["test_start"], "end": fold["test_end"], "params": params}
        )

    oos = simulate_strategy(
        opens,
        closes,
        args.start_oos,
        args.end_oos,
        cost_rate,
        args.min_universe_coverage,
        schedule=schedule,
    )
    benchmark = simulate_benchmark(
        opens, closes, args.start_oos, args.end_oos, cost_rate
    )
    strategy_metrics = performance_metrics(oos["equity"], oos["returns"])
    benchmark_metrics = performance_metrics(
        benchmark["equity"], benchmark["returns"]
    )
    coverage_values = [item["coverage"] for item in oos["rebalances"]]

    result = {
        "experiment": {
            "name": "historical_dow_cross_sectional_momentum_walk_forward",
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "oos_start": args.start_oos,
            "oos_end": args.end_oos,
            "training_window_years": args.train_years,
            "test_window": "non-overlapping calendar year",
            "parameter_selection": "highest training Sharpe; deterministic tie-breaks",
            "parameter_grid_size": len(DEFAULT_PARAMETER_GRID),
            "signal_timing": "previous trading close",
            "execution_timing": "next trading open",
            "rebalance": "monthly",
            "weighting": "equal weight at 1/top_n; negative momentum capacity remains cash",
            "fractional_shares": True,
            "commission_bps_each_trade": args.commission_bps,
            "slippage_bps_each_trade": args.slippage_bps,
        },
        "data": {
            "price_source": PRICE_SOURCE,
            "universe_source": UNIVERSE_SOURCE,
            "downloaded_at_utc": downloaded_at,
            "data_mode": data_mode,
            "cache_path": str(cache_path.resolve()),
            "cache_sha256": cache_hash,
            "download_start": download_start,
            "failed_tickers": failed_tickers,
            "universe_aliases": UNIVERSE_ALIASES,
            "minimum_universe_coverage": args.min_universe_coverage,
            "average_oos_coverage": float(np.mean(coverage_values)),
            "minimum_oos_coverage_observed": float(np.min(coverage_values)),
            "strict_point_in_time_scope": [
                "historical membership effective dates",
                "prices at or before each signal date",
                "next-open execution",
            ],
            "not_vintage_versioned": [
                "Yahoo corporate-action adjustments and later vendor corrections",
                "Wikipedia membership page revisions",
            ],
            "excluded_non_point_in_time_fields": [
                "fundamentals", "news", "insider data", "current market cap", "current sectors"
            ],
        },
        "oos_strategy": {
            "metrics": strategy_metrics,
            "block_bootstrap_cagr_95pct": block_bootstrap_cagr(
                oos["returns"], samples=args.bootstrap_samples
            ),
            "total_turnover": oos["total_turnover"],
            "transaction_cost_fraction_of_initial_capital": oos["total_transaction_cost"],
            "rebalance_count": len(oos["rebalances"]),
        },
        "benchmark_dia": {
            "metrics": benchmark_metrics,
            "entry_cost_fraction_of_initial_capital": benchmark["entry_cost"],
        },
        "comparison": {
            "cagr_difference": strategy_metrics["cagr"] - benchmark_metrics["cagr"],
            "total_return_difference": (
                strategy_metrics["total_return"] - benchmark_metrics["total_return"]
            ),
            "max_drawdown_improvement": (
                strategy_metrics["max_drawdown"] - benchmark_metrics["max_drawdown"]
            ),
        },
        "folds": selected_folds,
        "validity": {
            "lookahead_bias_controlled": True,
            "non_overlapping_oos_folds": True,
            "historical_membership_used": True,
            "current_constituent_survivorship_bias": False,
            "fundamental_point_in_time_tested": False,
            "vendor_vintage_archive_used": False,
            "investment_claim": "research evidence only; not a highest-return guarantee",
        },
    }

    sensitivity_values = [
        float(value.strip())
        for value in args.sensitivity_total_cost_bps.split(",")
        if value.strip()
    ]
    if sensitivity_values:
        result["cost_sensitivity"] = run_cost_sensitivity(
            opens,
            closes,
            folds,
            sensitivity_values,
            args.min_universe_coverage,
        )
    if args.fixed_grid_diagnostics:
        result["fixed_grid_oos_diagnostics"] = {
            "warning": "OOS diagnostic only; these rows must not be used to select a winner.",
            "results": fixed_grid_diagnostics(
                opens,
                closes,
                args.start_oos,
                args.end_oos,
                cost_rate,
                args.min_universe_coverage,
            ),
        }

    result_path = output_dir / "walk_forward_results.json"
    result_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, default=_json_default),
        encoding="utf-8",
    )
    equity_frame = pd.concat([oos["equity"], benchmark["equity"]], axis=1)
    equity_frame["strategy_return"] = oos["returns"]
    equity_frame["benchmark_return"] = benchmark["returns"]
    equity_frame.to_csv(output_dir / "oos_equity.csv", index_label="date")
    pd.DataFrame(oos["rebalances"]).to_csv(
        output_dir / "oos_rebalances.csv", index=False
    )
    (output_dir / "universe_schedule.json").write_text(
        json.dumps(
            {
                "source": UNIVERSE_SOURCE,
                "initial_effective_date": "2013-09-23",
                "initial_members": sorted(INITIAL_DOW_MEMBERS),
                "changes": [
                    {"effective_date": date, "added": sorted(added), "removed": sorted(removed)}
                    for date, added, removed in DOW_CHANGES
                ],
                "aliases": UNIVERSE_ALIASES,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return result


def print_summary(result: dict) -> None:
    strategy = result["oos_strategy"]["metrics"]
    benchmark = result["benchmark_dia"]["metrics"]
    comparison = result["comparison"]
    print("\nWalk-forward OOS validation")
    print(f"Period: {result['experiment']['oos_start']} ~ {result['experiment']['oos_end']}")
    print(
        "Strategy: "
        f"CAGR {strategy['cagr']:.2%}, total {strategy['total_return']:.2%}, "
        f"Sharpe {strategy['sharpe_ratio']:.2f}, MDD {strategy['max_drawdown']:.2%}"
    )
    print(
        "DIA:      "
        f"CAGR {benchmark['cagr']:.2%}, total {benchmark['total_return']:.2%}, "
        f"Sharpe {benchmark['sharpe_ratio']:.2f}, MDD {benchmark['max_drawdown']:.2%}"
    )
    print(f"CAGR difference: {comparison['cagr_difference']:+.2%}")
    print(
        "Coverage: "
        f"avg {result['data']['average_oos_coverage']:.1%}, "
        f"min {result['data']['minimum_oos_coverage_observed']:.1%}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Historical-membership, next-open walk-forward OOS validation"
    )
    parser.add_argument("--start-oos", default="2018-01-01")
    parser.add_argument("--end-oos", default="2025-12-31")
    parser.add_argument("--train-years", type=int, default=3)
    parser.add_argument("--commission-bps", type=float, default=5.0)
    parser.add_argument("--slippage-bps", type=float, default=5.0)
    parser.add_argument("--min-universe-coverage", type=float, default=0.90)
    parser.add_argument("--bootstrap-samples", type=int, default=1000)
    parser.add_argument(
        "--sensitivity-total-cost-bps",
        default="",
        help="comma-separated total one-way costs, e.g. 0,25",
    )
    parser.add_argument("--fixed-grid-diagnostics", action="store_true")
    parser.add_argument(
        "--output-dir", default="artifacts/walk_forward/dow_momentum_2018_2025"
    )
    parser.add_argument("--refresh-data", action="store_true")
    args = parser.parse_args()

    if pd.Timestamp(args.start_oos) > pd.Timestamp(args.end_oos):
        parser.error("start-oos cannot be later than end-oos")
    if args.train_years < 1:
        parser.error("train-years must be at least 1")
    if args.commission_bps < 0 or args.slippage_bps < 0:
        parser.error("cost inputs cannot be negative")
    if not 0 < args.min_universe_coverage <= 1:
        parser.error("min-universe-coverage must be in (0, 1]")
    if args.bootstrap_samples < 100:
        parser.error("bootstrap-samples must be at least 100")
    try:
        sensitivity_costs = [
            float(value.strip())
            for value in args.sensitivity_total_cost_bps.split(",")
            if value.strip()
        ]
    except ValueError:
        parser.error("sensitivity-total-cost-bps must be comma-separated numbers")
    if any(value < 0 for value in sensitivity_costs):
        parser.error("sensitivity costs cannot be negative")
    earliest_training = pd.Timestamp(args.start_oos) - pd.DateOffset(years=args.train_years)
    if earliest_training < pd.Timestamp("2015-01-01"):
        parser.error("the frozen membership schedule supports training from 2015-01-01")

    result = run_walk_forward(args)
    print_summary(result)


if __name__ == "__main__":
    main()
