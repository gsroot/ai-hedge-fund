#!/usr/bin/env python3
"""SEC filed-date fundamentals + prices in a cost-aware walk-forward test."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd
import yfinance as yf


SCRIPT_DIR = Path(__file__).resolve().parent
PREDICT_SCRIPTS = SCRIPT_DIR.parents[1] / "predict" / "scripts"
if str(PREDICT_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(PREDICT_SCRIPTS))

import sec_point_in_time as sec_pit  # noqa: E402


def _load_walk_forward_module():
    path = SCRIPT_DIR / "walk_forward.py"
    spec = importlib.util.spec_from_file_location("financial_skill_walk_forward_core", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


wf = _load_walk_forward_module()


@dataclass(frozen=True)
class MultifactorParams:
    style: str
    value_weight: float
    quality_weight: float
    growth_weight: float
    momentum_weight: float
    low_vol_weight: float
    momentum_lookback: int
    top_n: int
    weighting: str
    market_filter: bool


STYLE_WEIGHTS = {
    "value_quality": (0.35, 0.35, 0.10, 0.15, 0.05),
    "balanced": (0.25, 0.25, 0.20, 0.25, 0.05),
    "growth_momentum": (0.10, 0.20, 0.30, 0.35, 0.05),
    "quality_momentum": (0.15, 0.35, 0.10, 0.30, 0.10),
    "fundamental": (0.40, 0.40, 0.20, 0.00, 0.00),
    "momentum_low_vol": (0.00, 0.00, 0.00, 0.75, 0.25),
}

PARAMETER_GRID = tuple(
    MultifactorParams(
        style=style,
        value_weight=weights[0],
        quality_weight=weights[1],
        growth_weight=weights[2],
        momentum_weight=weights[3],
        low_vol_weight=weights[4],
        momentum_lookback=252 if style != "growth_momentum" else 126,
        top_n=top_n,
        weighting=weighting,
        market_filter=market_filter,
    )
    for style, weights in STYLE_WEIGHTS.items()
    for top_n in (8, 12)
    for weighting in ("equal", "score_inverse_vol")
    for market_filter in (False, True)
)

EVIDENCE_MIN_OOS_DAYS = 126
EVIDENCE_MIN_OUTPERFORMANCE_PROBABILITY = 0.80


def download_raw_closes(
    tickers: Iterable[str], start_date: str, end_date: str
) -> tuple[pd.DataFrame, list[str]]:
    requested = sorted(set(ticker.upper() for ticker in tickers))
    end_exclusive = (pd.Timestamp(end_date) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    series = {}
    failed = []
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
        values = raw.get("Close") if not raw.empty else None
        if isinstance(values, pd.Series):
            values = values.to_frame(name=batch[0])
        if values is None:
            failed.extend(batch)
            continue
        values.columns = [str(column).upper() for column in values.columns]
        for ticker in batch:
            if ticker not in values or values[ticker].dropna().empty:
                failed.append(ticker)
            else:
                series[ticker] = pd.to_numeric(values[ticker], errors="coerce")
    frame = pd.DataFrame(series).sort_index()
    frame.index = pd.DatetimeIndex(frame.index).tz_localize(None).normalize()
    return frame, sorted(set(failed))


def load_or_download_raw_closes(
    path: Path,
    tickers: Iterable[str],
    start_date: str,
    end_date: str,
    refresh: bool,
) -> tuple[pd.DataFrame, list[str]]:
    if path.exists() and not refresh:
        frame = pd.read_csv(path, index_col=0, parse_dates=True)
        frame.columns = [str(column).upper() for column in frame.columns]
        failed = sorted(set(tickers) - set(frame.columns))
        return frame, failed
    frame, failed = download_raw_closes(tickers, start_date, end_date)
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index_label="date")
    return frame, failed


def merge_supplemental_price_sources(
    opens: pd.DataFrame,
    closes: pd.DataFrame,
    raw_closes: pd.DataFrame,
    specs: Iterable[str],
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, list[dict]]:
    """Fill vendor gaps from explicit, locally cached OHLC CSV sources.

    Each spec is ``TICKER=path``. Existing Yahoo observations win; supplemental
    rows only fill missing values. The input must contain Date, Open, Close and
    Adj Close so adjusted opens can be calculated without look-ahead.
    """
    merged_opens = opens.copy()
    merged_closes = closes.copy()
    merged_raw = raw_closes.copy()
    metadata = []
    for spec in specs:
        ticker, separator, raw_path = spec.partition("=")
        ticker = ticker.strip().upper()
        path = Path(raw_path.strip())
        if not separator or not ticker or not raw_path.strip():
            raise ValueError(
                f"Invalid supplemental price spec {spec!r}; expected TICKER=path"
            )
        if not path.exists():
            raise FileNotFoundError(path)
        frame = pd.read_csv(path)
        required = {"Date", "Open", "Close", "Adj Close"}
        missing = required - set(frame.columns)
        if missing:
            raise ValueError(f"{path} is missing columns: {sorted(missing)}")
        dates = pd.to_datetime(frame["Date"], errors="coerce")
        raw_open = pd.to_numeric(frame["Open"], errors="coerce")
        raw_close = pd.to_numeric(frame["Close"], errors="coerce")
        adjusted_close = pd.to_numeric(frame["Adj Close"], errors="coerce")
        adjustment = adjusted_close / raw_close.replace(0, np.nan)
        adjusted_open = raw_open * adjustment
        supplemental = pd.DataFrame(
            {
                "open": adjusted_open.to_numpy(),
                "close": adjusted_close.to_numpy(),
                "raw_close": raw_close.to_numpy(),
            },
            index=pd.DatetimeIndex(dates).tz_localize(None).normalize(),
        ).dropna(how="all")
        supplemental = supplemental[~supplemental.index.duplicated(keep="last")]
        if supplemental[["open", "close"]].dropna().empty:
            raise ValueError(f"{path} contains no usable adjusted OHLC rows")
        merged_index = merged_opens.index.union(supplemental.index)
        merged_opens = merged_opens.reindex(merged_index)
        merged_closes = merged_closes.reindex(merged_index)
        merged_raw = merged_raw.reindex(merged_raw.index.union(supplemental.index))
        existing_open = (
            merged_opens[ticker]
            if ticker in merged_opens
            else pd.Series(index=merged_index, dtype=float)
        )
        existing_close = (
            merged_closes[ticker]
            if ticker in merged_closes
            else pd.Series(index=merged_index, dtype=float)
        )
        existing_raw = (
            merged_raw[ticker]
            if ticker in merged_raw
            else pd.Series(index=merged_raw.index, dtype=float)
        )
        merged_opens[ticker] = existing_open.combine_first(supplemental["open"])
        merged_closes[ticker] = existing_close.combine_first(supplemental["close"])
        merged_raw[ticker] = existing_raw.combine_first(supplemental["raw_close"])
        metadata.append(
            {
                "ticker": ticker,
                "path": str(path.resolve()),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "rows": int(len(supplemental)),
                "first_date": supplemental.index.min().strftime("%Y-%m-%d"),
                "last_date": supplemental.index.max().strftime("%Y-%m-%d"),
                "merge_policy": "fill_missing_only_yahoo_wins",
            }
        )
    return (
        merged_opens.sort_index(),
        merged_closes.sort_index(),
        merged_raw.sort_index(),
        metadata,
    )


def _rank(frame: pd.DataFrame, column: str, higher_is_better: bool = True) -> pd.Series:
    values = pd.to_numeric(frame[column], errors="coerce")
    ranks = values.rank(pct=True, method="average")
    return ranks if higher_is_better else 1.0 - ranks


def _row_mean(frame: pd.DataFrame, columns: list[str], minimum: int) -> pd.Series:
    values = frame[columns]
    result = values.mean(axis=1, skipna=True)
    return result.where(values.notna().sum(axis=1) >= minimum)


def _momentum(
    close: pd.Series, signal_date: pd.Timestamp, lookback: int, skip_recent: int = 21
) -> float | None:
    history = close.loc[:signal_date].dropna()
    end_position = len(history) - 1 - skip_recent
    start_position = end_position - lookback
    if start_position < 0 or end_position < 0:
        return None
    start = float(history.iloc[start_position])
    end = float(history.iloc[end_position])
    return end / start - 1.0 if start > 0 and end > 0 else None


def _annualized_volatility(
    close: pd.Series, signal_date: pd.Timestamp, observations: int = 126
) -> float | None:
    history = close.loc[:signal_date].dropna().pct_change(fill_method=None).dropna()
    if len(history) < observations:
        return None
    value = float(history.iloc[-observations:].std(ddof=1) * math.sqrt(252))
    return value if value > 0 and math.isfinite(value) else None


def _raw_price(raw_closes: pd.DataFrame, date: pd.Timestamp, ticker: str) -> float | None:
    if ticker not in raw_closes:
        return None
    history = raw_closes[ticker].loc[:date].dropna()
    if history.empty:
        return None
    value = float(history.iloc[-1])
    return value if value > 0 else None


def build_factor_panel(
    opens: pd.DataFrame,
    closes: pd.DataFrame,
    raw_closes: pd.DataFrame,
    sec_cache: Path,
    start_date: str,
    end_date: str,
) -> pd.DataFrame:
    calendar = pd.DatetimeIndex(closes.index).sort_values()
    calendar = calendar[closes["DIA"].notna().reindex(calendar, fill_value=False)]
    dates = calendar[
        (calendar >= pd.Timestamp(start_date)) & (calendar <= pd.Timestamp(end_date))
    ]
    payload_cache: dict[tuple[str, int], dict[str, Any]] = {}
    records = []
    for execution_date in sorted(wf.month_open_dates(dates)):
        earlier = calendar[calendar < execution_date]
        if len(earlier) == 0:
            continue
        signal_date = earlier[-1]
        members = sorted(wf.dow_members_as_of(signal_date))
        for ticker in members:
            if ticker not in closes or wf._valid_price(opens, execution_date, ticker) is None:
                continue
            cik = sec_pit.cik_for_ticker(ticker, signal_date)
            cache_key = (ticker, cik)
            if cache_key not in payload_cache:
                payload_cache[cache_key] = sec_pit.load_companyfacts(
                    sec_cache, ticker, signal_date
                )
            snapshot = sec_pit.fundamental_snapshot(
                payload_cache[cache_key],
                signal_date,
                _raw_price(raw_closes, signal_date, ticker),
            )
            row = {
                "execution_date": execution_date,
                "signal_date": signal_date,
                "ticker": ticker,
                "data_quality": snapshot["data_quality"],
                "latest_filed_date": snapshot["latest_filed_date"],
                "latest_annual_period_end": snapshot["latest_annual_period_end"],
                "momentum_126": _momentum(closes[ticker], signal_date, 126),
                "momentum_252": _momentum(closes[ticker], signal_date, 252),
                "annualized_volatility": _annualized_volatility(
                    closes[ticker], signal_date
                ),
            }
            row.update(snapshot["metrics"])
            records.append(row)

    raw = pd.DataFrame(records)
    if raw.empty:
        raise ValueError("No point-in-time factor rows were built")
    ranked_frames = []
    for execution_date, group in raw.groupby("execution_date", sort=True):
        group = group.copy()
        higher = {
            "earnings_yield": "rank_earnings_yield",
            "free_cash_flow_yield": "rank_free_cash_flow_yield",
            "sales_yield": "rank_sales_yield",
            "return_on_assets": "rank_return_on_assets",
            "operating_margin": "rank_operating_margin",
            "free_cash_flow_margin": "rank_free_cash_flow_margin",
            "revenue_growth": "rank_revenue_growth",
            "net_income_growth": "rank_net_income_growth",
            "momentum_126": "rank_momentum_126",
            "momentum_252": "rank_momentum_252",
        }
        lower = {
            "liabilities_to_assets": "rank_low_leverage",
            "accruals_to_assets": "rank_low_accruals",
            "annualized_volatility": "rank_low_volatility",
        }
        for source, target in higher.items():
            group[target] = _rank(group, source, True)
        for source, target in lower.items():
            group[target] = _rank(group, source, False)
        group["value_factor"] = _row_mean(
            group,
            ["rank_earnings_yield", "rank_free_cash_flow_yield", "rank_sales_yield"],
            1,
        )
        group["quality_factor"] = _row_mean(
            group,
            [
                "rank_return_on_assets",
                "rank_operating_margin",
                "rank_free_cash_flow_margin",
                "rank_low_leverage",
                "rank_low_accruals",
            ],
            2,
        )
        group["growth_factor"] = _row_mean(
            group, ["rank_revenue_growth", "rank_net_income_growth"], 1
        )
        ranked_frames.append(group)
    return pd.concat(ranked_frames, ignore_index=True).sort_values(
        ["execution_date", "ticker"]
    )


def _capped_allocation(
    raw_scores: dict[str, float], gross_target: float, cap: float = 0.15
) -> dict[str, float]:
    allocations = {ticker: 0.0 for ticker in raw_scores}
    active = {ticker for ticker, score in raw_scores.items() if score > 0}
    remaining = gross_target
    while active and remaining > 1e-12:
        total = sum(raw_scores[ticker] for ticker in active)
        if total <= 0:
            break
        proposed = {
            ticker: remaining * raw_scores[ticker] / total for ticker in active
        }
        fraction = min(
            1.0,
            *(
                (cap - allocations[ticker]) / amount
                for ticker, amount in proposed.items()
                if amount > 0
            ),
        )
        added = 0.0
        for ticker, amount in proposed.items():
            increment = max(0.0, amount * fraction)
            allocations[ticker] += increment
            added += increment
        remaining -= added
        active = {
            ticker for ticker in active if allocations[ticker] < cap - 1e-12
        }
        if added <= 1e-12 or fraction >= 1.0 - 1e-12:
            break
    return {ticker: weight for ticker, weight in allocations.items() if weight > 1e-12}


def equal_weight_schedule(
    factor_panel: pd.DataFrame,
    start_date: str,
    end_date: str,
) -> dict[pd.Timestamp, dict]:
    """Build a fixed monthly equal-weight baseline from historical members."""
    start = pd.Timestamp(start_date)
    end = pd.Timestamp(end_date)
    schedule = {}
    for execution_date, group in factor_panel.groupby("execution_date", sort=True):
        execution_date = pd.Timestamp(execution_date)
        if not start <= execution_date <= end:
            continue
        selected = sorted(group["ticker"].unique())
        if not selected:
            continue
        schedule[execution_date] = {
            "weights": {ticker: 1.0 / len(selected) for ticker in selected},
            "detail": {
                "signal_date": pd.Timestamp(group["signal_date"].iloc[0]).strftime(
                    "%Y-%m-%d"
                ),
                "execution_date": execution_date.strftime("%Y-%m-%d"),
                "model": "historical_dow_equal_weight_baseline",
                "selected": selected,
                "target_invested_weight": 1.0,
            },
        }
    return schedule


def universe_coverage_summary(factor_panel: pd.DataFrame) -> dict:
    """Summarize whether every historical 30-stock member has a usable row."""
    counts = factor_panel.groupby("execution_date")["ticker"].nunique().sort_index()
    coverage = counts / 30.0
    incomplete = counts[counts < 30]
    return {
        "average": float(coverage.mean()),
        "minimum": float(coverage.min()),
        "incomplete_months": int(len(incomplete)),
        "incomplete_dates": {
            pd.Timestamp(date).strftime("%Y-%m-%d"): int(count)
            for date, count in incomplete.items()
        },
    }


def assess_evidence(
    strategy_metrics: dict,
    dia_metrics: dict,
    equal_weight_metrics: dict,
    paired_dia: dict,
    paired_equal_weight: dict,
    universe_coverage: dict,
    independent_holdout: bool,
    oos_observations: int,
) -> dict:
    """Grade empirical support without blocking portfolio construction."""
    checks = {
        "complete_historical_universe": universe_coverage["minimum"] >= 1.0,
        "beats_dia_total_return": (
            strategy_metrics["total_return"] > dia_metrics["total_return"]
        ),
        "beats_equal_weight_total_return": (
            strategy_metrics["total_return"] > equal_weight_metrics["total_return"]
        ),
        "drawdown_no_worse_than_dia": (
            strategy_metrics["max_drawdown"] >= dia_metrics["max_drawdown"]
        ),
        "drawdown_no_worse_than_equal_weight": (
            strategy_metrics["max_drawdown"]
            >= equal_weight_metrics["max_drawdown"]
        ),
        "independent_holdout_declared": bool(independent_holdout),
        "minimum_126_oos_days": oos_observations >= EVIDENCE_MIN_OOS_DAYS,
        "outperformance_probability_vs_dia_at_least_80pct": (
            paired_dia["probability_greater_than_zero"] is not None
            and paired_dia["probability_greater_than_zero"]
            >= EVIDENCE_MIN_OUTPERFORMANCE_PROBABILITY
        ),
        "outperformance_probability_vs_equal_weight_at_least_80pct": (
            paired_equal_weight["probability_greater_than_zero"] is not None
            and paired_equal_weight["probability_greater_than_zero"]
            >= EVIDENCE_MIN_OUTPERFORMANCE_PROBABILITY
        ),
        "minimum_three_oos_years": strategy_metrics["years_observed"] >= 3,
        "paired_ci_low_above_zero_vs_dia": (
            paired_dia["low"] is not None and paired_dia["low"] > 0
        ),
        "paired_ci_low_above_zero_vs_equal_weight": (
            paired_equal_weight["low"] is not None
            and paired_equal_weight["low"] > 0
        ),
    }
    preliminary_keys = (
        "complete_historical_universe",
        "beats_dia_total_return",
        "beats_equal_weight_total_return",
    )
    promising_keys = preliminary_keys + (
        "drawdown_no_worse_than_dia",
        "drawdown_no_worse_than_equal_weight",
        "independent_holdout_declared",
        "minimum_126_oos_days",
        "outperformance_probability_vs_dia_at_least_80pct",
        "outperformance_probability_vs_equal_weight_at_least_80pct",
    )
    robust_keys = promising_keys + (
        "minimum_three_oos_years",
        "paired_ci_low_above_zero_vs_dia",
        "paired_ci_low_above_zero_vs_equal_weight",
    )
    preliminary = all(checks[key] for key in preliminary_keys)
    promising = all(checks[key] for key in promising_keys)
    robust = all(checks[key] for key in robust_keys)
    if robust:
        grade = "robust"
        interpretation = "long-independent-oos-with-positive-paired-ci"
    elif promising:
        grade = "promising"
        interpretation = "short-independent-oos-with-probabilistic-edge"
    elif preliminary:
        grade = "preliminary"
        interpretation = "benchmark-beating-but-confirmation-incomplete"
    else:
        grade = "weak"
        interpretation = "benchmark-edge-not-demonstrated"
    return {
        "grade": grade,
        "interpretation": interpretation,
        "portfolio_construction_effect": "informational-only-does-not-block-output",
        "checks": checks,
        "grade_requirements": {
            "preliminary": list(preliminary_keys),
            "promising": list(promising_keys),
            "robust": list(robust_keys),
        },
    }


def portfolio_construction_payload(
    model_weights: dict[str, float], evidence_assessment: dict
) -> dict:
    """Build a full target portfolio; evidence is descriptive, not a blocker."""
    normalized_weights = {
        ticker: float(weight) for ticker, weight in model_weights.items()
    }
    total_weight = sum(normalized_weights.values())
    if any(weight < 0.0 for weight in normalized_weights.values()):
        raise ValueError("Portfolio weights must be non-negative")
    if total_weight > 1.0 + 1e-9:
        raise ValueError("Portfolio weights cannot exceed 100%")
    return {
        "status": "portfolio-ready",
        "portfolio_construction_eligible": True,
        "target_total_portfolio_fraction": 1.0,
        "weights": normalized_weights,
        "cash_weight": max(0.0, 1.0 - total_weight),
        "evidence_grade": evidence_assessment["grade"],
        "evidence_assessment": evidence_assessment,
    }


def build_weight_schedule(
    factor_panel: pd.DataFrame,
    closes: pd.DataFrame,
    start_date: str,
    end_date: str,
    params: MultifactorParams,
    minimum_factor_weight_coverage: float = 0.70,
) -> dict[pd.Timestamp, dict]:
    start = pd.Timestamp(start_date)
    end = pd.Timestamp(end_date)
    schedule = {}
    component_weights = {
        "value_factor": params.value_weight,
        "quality_factor": params.quality_weight,
        "growth_factor": params.growth_weight,
        f"rank_momentum_{params.momentum_lookback}": params.momentum_weight,
        "rank_low_volatility": params.low_vol_weight,
    }
    total_model_weight = sum(component_weights.values())
    for execution_date, group in factor_panel.groupby("execution_date", sort=True):
        execution_date = pd.Timestamp(execution_date)
        if not start <= execution_date <= end:
            continue
        group = group.copy().set_index("ticker")
        scores = {}
        coverage = {}
        for ticker, row in group.iterrows():
            available_weight = sum(
                weight
                for column, weight in component_weights.items()
                if weight > 0 and pd.notna(row.get(column))
            )
            coverage[ticker] = available_weight / total_model_weight
            if coverage[ticker] < minimum_factor_weight_coverage:
                continue
            weighted_score = sum(
                float(row[column]) * weight
                for column, weight in component_weights.items()
                if weight > 0 and pd.notna(row.get(column))
            )
            scores[ticker] = weighted_score / available_weight
        selected = sorted(scores, key=lambda ticker: (-scores[ticker], ticker))[: params.top_n]
        signal_date = pd.Timestamp(group["signal_date"].iloc[0])
        gross_target = 1.0
        market_filter_triggered = False
        if params.market_filter:
            dia = closes["DIA"].loc[:signal_date].dropna()
            if len(dia) >= 200 and float(dia.iloc[-1]) < float(dia.iloc[-200:].mean()):
                gross_target = 0.50
                market_filter_triggered = True
        if params.weighting == "equal":
            per_name = min(0.15, gross_target / params.top_n)
            weights = {ticker: per_name for ticker in selected}
        else:
            raw_scores = {
                ticker: scores[ticker]
                / max(float(group.at[ticker, "annualized_volatility"]), 0.10)
                for ticker in selected
                if pd.notna(group.at[ticker, "annualized_volatility"])
            }
            weights = _capped_allocation(raw_scores, gross_target)
        latest_filed_dates = {
            ticker: group.at[ticker, "latest_filed_date"] for ticker in selected
        }
        if any(
            date and pd.Timestamp(date) > signal_date for date in latest_filed_dates.values()
        ):
            raise AssertionError("future SEC filing entered multifactor schedule")
        schedule[execution_date] = {
            "weights": weights,
            "detail": {
                "signal_date": signal_date.strftime("%Y-%m-%d"),
                "execution_date": execution_date.strftime("%Y-%m-%d"),
                "parameters": asdict(params),
                "eligible_members": len(scores),
                "selected": selected,
                "composite_scores": {ticker: scores[ticker] for ticker in selected},
                "factor_weight_coverage": {ticker: coverage[ticker] for ticker in selected},
                "latest_filed_dates": latest_filed_dates,
                "target_invested_weight": sum(weights.values()),
                "market_filter_triggered": market_filter_triggered,
            },
        }
    return schedule


def select_parameters(
    factor_panel: pd.DataFrame,
    opens: pd.DataFrame,
    closes: pd.DataFrame,
    fold: dict,
    cost_rate: float,
) -> tuple[MultifactorParams, dict, list[dict]]:
    trials = []
    for params in PARAMETER_GRID:
        schedule = build_weight_schedule(
            factor_panel, closes, fold["train_start"], fold["train_end"], params
        )
        simulation = wf.simulate_weight_schedule(
            opens,
            closes,
            fold["train_start"],
            fold["train_end"],
            cost_rate,
            schedule,
        )
        metrics = wf.performance_metrics(simulation["equity"], simulation["returns"])
        trials.append(
            {
                "params": params,
                "metrics": metrics,
                "turnover": simulation["total_turnover"],
            }
        )
    best = max(
        trials,
        key=lambda trial: (
            trial["metrics"]["sharpe_ratio"],
            trial["metrics"]["cagr"],
            trial["metrics"]["max_drawdown"],
            -trial["turnover"],
        ),
    )
    return (
        best["params"],
        best["metrics"],
        [
            {
                "parameters": asdict(trial["params"]),
                "metrics": trial["metrics"],
                "turnover": trial["turnover"],
            }
            for trial in trials
        ],
    )


def _json_default(value):
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, pd.Timestamp):
        return value.strftime("%Y-%m-%d")
    raise TypeError(f"Cannot serialize {type(value)!r}")


def run(args: argparse.Namespace) -> dict:
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    folds = wf.make_folds(args.start_oos, args.end_oos, args.train_years)
    earliest_train = pd.Timestamp(folds[0]["train_start"])
    data_start = (earliest_train - pd.Timedelta(days=450)).strftime("%Y-%m-%d")
    tickers = wf.all_required_tickers(args.end_oos)

    adjusted_cache = (
        Path(args.adjusted_price_cache)
        if args.adjusted_price_cache
        else output_dir / "adjusted_ohlc.csv"
    )
    if adjusted_cache.exists() and not args.refresh_prices:
        opens, closes, adjusted_hash = wf.load_price_cache(adjusted_cache)
        adjusted_failed = sorted(set(tickers) - set(closes.columns))
    else:
        opens, closes, adjusted_failed = wf.download_adjusted_ohlc(
            tickers, data_start, args.end_oos
        )
        adjusted_hash = wf.save_price_cache(adjusted_cache, opens, closes)

    raw_cache = output_dir / "raw_close.csv"
    raw_closes, raw_failed = load_or_download_raw_closes(
        raw_cache, tickers, data_start, args.end_oos, args.refresh_prices
    )
    supplemental_metadata = []
    if args.supplemental_price:
        opens, closes, raw_closes, supplemental_metadata = (
            merge_supplemental_price_sources(
                opens, closes, raw_closes, args.supplemental_price
            )
        )
        adjusted_cache = output_dir / "combined_adjusted_ohlc.csv"
        adjusted_hash = wf.save_price_cache(adjusted_cache, opens, closes)
        raw_cache = output_dir / "combined_raw_close.csv"
        raw_closes.to_csv(raw_cache, index_label="date")
        adjusted_failed = sorted(
            ticker for ticker in tickers if ticker not in closes or closes[ticker].dropna().empty
        )
        raw_failed = sorted(
            ticker
            for ticker in tickers
            if ticker not in raw_closes or raw_closes[ticker].dropna().empty
        )
    sec_cache = Path(args.sec_cache) if args.sec_cache else output_dir / "sec_companyfacts"
    sec_manifest = sec_pit.download_companyfacts(
        sec_pit.CIK_BY_TICKER,
        sec_cache,
        refresh=args.refresh_sec,
    )
    if sec_manifest["failed"]:
        raise RuntimeError(f"SEC download failures: {sec_manifest['failed']}")

    panel_path = output_dir / "point_in_time_factor_panel.csv"
    factor_panel = build_factor_panel(
        opens,
        closes,
        raw_closes,
        sec_cache,
        folds[0]["train_start"],
        args.end_oos,
    )
    factor_panel.to_csv(panel_path, index=False, date_format="%Y-%m-%d")

    cost_rate = (args.commission_bps + args.slippage_bps) / 10000.0
    selected_folds = []
    selected_schedule = {}
    for fold in folds:
        params, training_metrics, trials = select_parameters(
            factor_panel, opens, closes, fold, cost_rate
        )
        test_schedule = build_weight_schedule(
            factor_panel, closes, fold["test_start"], fold["test_end"], params
        )
        test = wf.simulate_weight_schedule(
            opens,
            closes,
            fold["test_start"],
            fold["test_end"],
            cost_rate,
            test_schedule,
        )
        selected_schedule.update(test_schedule)
        selected_folds.append(
            {
                **fold,
                "selected_parameters": asdict(params),
                "training_metrics": training_metrics,
                "test_metrics_reset_at_fold_start": wf.performance_metrics(
                    test["equity"], test["returns"]
                ),
                "training_grid": trials,
            }
        )

    oos = wf.simulate_weight_schedule(
        opens,
        closes,
        args.start_oos,
        args.end_oos,
        cost_rate,
        selected_schedule,
    )
    benchmark = wf.simulate_benchmark(
        opens, closes, args.start_oos, args.end_oos, cost_rate
    )
    equal_weight = wf.simulate_weight_schedule(
        opens,
        closes,
        args.start_oos,
        args.end_oos,
        cost_rate,
        equal_weight_schedule(factor_panel, args.start_oos, args.end_oos),
    )
    strategy_metrics = wf.performance_metrics(oos["equity"], oos["returns"])
    benchmark_metrics = wf.performance_metrics(
        benchmark["equity"], benchmark["returns"]
    )
    equal_weight_metrics = wf.performance_metrics(
        equal_weight["equity"], equal_weight["returns"]
    )
    universe_coverage = universe_coverage_summary(factor_panel)
    paired_dia = wf.paired_block_bootstrap_cagr_difference(
        oos["returns"], benchmark["returns"], samples=args.bootstrap_samples
    )
    paired_equal_weight = wf.paired_block_bootstrap_cagr_difference(
        oos["returns"], equal_weight["returns"], samples=args.bootstrap_samples
    )
    evidence_assessment = assess_evidence(
        strategy_metrics,
        benchmark_metrics,
        equal_weight_metrics,
        paired_dia,
        paired_equal_weight,
        universe_coverage,
        bool(args.independent_holdout),
        int(oos["returns"].dropna().shape[0]),
    )
    latest_execution_date = max(selected_schedule)
    latest_target = selected_schedule[latest_execution_date]
    model_weights = latest_target["weights"]
    portfolio_payload = portfolio_construction_payload(
        model_weights, evidence_assessment
    )
    candidate_path = output_dir / "multifactor_latest_candidate.json"
    latest_candidate = {
        "model_id": "sec_pit_multifactor_v1",
        **portfolio_payload,
        "signal_date": latest_target["detail"]["signal_date"],
        "execution_date": latest_execution_date.strftime("%Y-%m-%d"),
        "configuration": latest_target["detail"]["parameters"],
        "validation_result": str(
            (output_dir / "multifactor_walk_forward_results.json").resolve()
        ),
    }
    result = {
        "experiment": {
            "name": "sec_point_in_time_multifactor_walk_forward",
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "oos_start": args.start_oos,
            "oos_end": args.end_oos,
            "training_window_years": args.train_years,
            "test_window": "non-overlapping calendar year",
            "parameter_grid_size": len(PARAMETER_GRID),
            "factors": ["value", "quality", "growth", "momentum", "low_volatility"],
            "signal_timing": "previous trading close and SEC filed <= signal date",
            "execution_timing": "next trading open",
            "commission_bps": args.commission_bps,
            "slippage_bps": args.slippage_bps,
            "max_name_weight": 0.15,
            "research_iteration": (
                "independent_holdout" if args.independent_holdout else "development"
            ),
        },
        "data": {
            "sec_source": "https://data.sec.gov/api/xbrl/companyfacts/CIK##########.json",
            "sec_manifest": str((sec_cache / "manifest.json").resolve()),
            "adjusted_price_cache": str(adjusted_cache.resolve()),
            "adjusted_price_cache_sha256": adjusted_hash,
            "raw_price_cache": str(raw_cache.resolve()),
            "factor_panel": str(panel_path.resolve()),
            "latest_candidate": str(candidate_path.resolve()),
            "adjusted_price_failures": adjusted_failed,
            "raw_price_failures": raw_failed,
            "supplemental_price_sources": supplemental_metadata,
            "factor_rows": len(factor_panel),
            "fundamental_quality": factor_panel["data_quality"].value_counts().to_dict(),
            "historical_universe_coverage": universe_coverage,
        },
        "oos_strategy": {
            "metrics": strategy_metrics,
            "block_bootstrap_cagr_95pct": wf.block_bootstrap_cagr(
                oos["returns"], samples=args.bootstrap_samples
            ),
            "total_turnover": oos["total_turnover"],
            "transaction_cost_fraction_of_initial_capital": oos[
                "total_transaction_cost"
            ],
            "rebalance_count": len(oos["rebalances"]),
        },
        "benchmark_dia": {"metrics": benchmark_metrics},
        "benchmark_historical_dow_equal_weight": {
            "metrics": equal_weight_metrics,
            "total_turnover": equal_weight["total_turnover"],
            "transaction_cost_fraction_of_initial_capital": equal_weight[
                "total_transaction_cost"
            ],
        },
        "comparison": {
            "cagr_difference": strategy_metrics["cagr"] - benchmark_metrics["cagr"],
            "total_return_difference": (
                strategy_metrics["total_return"] - benchmark_metrics["total_return"]
            ),
            "max_drawdown_improvement": (
                strategy_metrics["max_drawdown"] - benchmark_metrics["max_drawdown"]
            ),
            "cagr_difference_vs_equal_weight": (
                strategy_metrics["cagr"] - equal_weight_metrics["cagr"]
            ),
            "paired_block_bootstrap_cagr_difference_vs_dia_95pct": paired_dia,
            "paired_block_bootstrap_cagr_difference_vs_equal_weight_95pct": (
                paired_equal_weight
            ),
        },
        "evidence_assessment": evidence_assessment,
        "folds": selected_folds,
        "validity": {
            "sec_filed_date_enforced": True,
            "lookahead_bias_controlled": True,
            "historical_membership_used": True,
            "non_overlapping_oos_folds": True,
            "vendor_vintage_archive_used_for_prices": False,
            "qualitative_investor_analysis_tested": False,
            "investment_claim": "research evidence only; not a highest-return guarantee",
        },
    }
    result_path = output_dir / "multifactor_walk_forward_results.json"
    result_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, default=_json_default),
        encoding="utf-8",
    )
    candidate_path.write_text(
        json.dumps(latest_candidate, ensure_ascii=False, indent=2, default=_json_default),
        encoding="utf-8",
    )
    equity = pd.concat([oos["equity"], benchmark["equity"]], axis=1)
    equity["strategy_return"] = oos["returns"]
    equity["benchmark_return"] = benchmark["returns"]
    equity.to_csv(output_dir / "multifactor_oos_equity.csv", index_label="date")
    pd.DataFrame(oos["rebalances"]).to_csv(
        output_dir / "multifactor_oos_rebalances.csv", index=False
    )
    return result


def print_summary(result: dict) -> None:
    strategy = result["oos_strategy"]["metrics"]
    benchmark = result["benchmark_dia"]["metrics"]
    comparison = result["comparison"]
    print("\nSEC point-in-time multifactor walk-forward")
    print(
        f"Strategy CAGR {strategy['cagr']:.2%}, total {strategy['total_return']:.2%}, "
        f"Sharpe {strategy['sharpe_ratio']:.2f}, MDD {strategy['max_drawdown']:.2%}"
    )
    print(
        f"DIA      CAGR {benchmark['cagr']:.2%}, total {benchmark['total_return']:.2%}, "
        f"Sharpe {benchmark['sharpe_ratio']:.2f}, MDD {benchmark['max_drawdown']:.2%}"
    )
    print(f"CAGR difference {comparison['cagr_difference']:+.2%}")
    evidence = result["evidence_assessment"]
    print(f"Evidence grade: {evidence['grade']} ({evidence['interpretation']})")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="SEC filed-date multifactor walk-forward OOS validation"
    )
    parser.add_argument("--start-oos", default="2018-01-01")
    parser.add_argument("--end-oos", default="2025-12-31")
    parser.add_argument("--train-years", type=int, default=3)
    parser.add_argument("--commission-bps", type=float, default=5.0)
    parser.add_argument("--slippage-bps", type=float, default=5.0)
    parser.add_argument("--bootstrap-samples", type=int, default=2000)
    parser.add_argument(
        "--independent-holdout",
        action="store_true",
        help="Declare that this date range was frozen before inspecting its results",
    )
    parser.add_argument("--adjusted-price-cache", default="")
    parser.add_argument("--sec-cache", default="")
    parser.add_argument(
        "--supplemental-price",
        action="append",
        default=[],
        metavar="TICKER=CSV",
        help="Fill missing Yahoo history from a Date/Open/Close/Adj Close CSV",
    )
    parser.add_argument(
        "--output-dir", default="artifacts/walk_forward/dow_multifactor_2018_2025"
    )
    parser.add_argument("--refresh-prices", action="store_true")
    parser.add_argument("--refresh-sec", action="store_true")
    args = parser.parse_args()
    if pd.Timestamp(args.start_oos) > pd.Timestamp(args.end_oos):
        parser.error("start-oos cannot be later than end-oos")
    if args.train_years < 1:
        parser.error("train-years must be at least 1")
    if args.commission_bps < 0 or args.slippage_bps < 0:
        parser.error("costs cannot be negative")
    if args.bootstrap_samples < 100:
        parser.error("bootstrap-samples must be at least 100")
    if pd.Timestamp(args.start_oos) - pd.DateOffset(years=args.train_years) < pd.Timestamp(
        "2015-01-01"
    ):
        parser.error("the frozen historical universe supports training from 2015-01-01")
    result = run(args)
    print_summary(result)


if __name__ == "__main__":
    main()
