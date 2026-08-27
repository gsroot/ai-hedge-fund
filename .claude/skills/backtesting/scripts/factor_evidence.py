#!/usr/bin/env python3
"""Create unified OOS evidence for every predict ranking factor."""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


SCRIPT_DIR = Path(__file__).resolve().parent
PREDICT_FACTOR_EVIDENCE = (
    Path(__file__).resolve().parents[2]
    / "predict"
    / "scripts"
    / "factor_evidence.py"
)


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


policy = _load_module("predict_factor_evidence_policy", PREDICT_FACTOR_EVIDENCE)
FACTOR_NAMES = policy.FACTOR_NAMES
REQUIRED_COLUMNS = {
    "signal_date",
    "execution_date",
    "label_end_date",
    "ticker",
    "forward_return",
    *FACTOR_NAMES,
}


def validate_factor_panel(panel: pd.DataFrame) -> pd.DataFrame:
    """Validate timing and shape without inferring missing point-in-time fields."""
    missing = sorted(REQUIRED_COLUMNS - set(panel.columns))
    if missing:
        raise ValueError(f"factor panel is missing columns: {missing}")
    result = panel.copy()
    for column in ("signal_date", "execution_date", "label_end_date"):
        result[column] = pd.to_datetime(result[column], errors="raise")
    if result.empty:
        raise ValueError("factor panel is empty")
    result["ticker"] = result["ticker"].astype(str).str.strip()
    if (result["ticker"] == "").any():
        raise ValueError("ticker must be non-empty")
    if result[["execution_date", "ticker"]].duplicated().any():
        raise ValueError("factor panel has duplicate execution_date/ticker rows")
    if not (result["signal_date"] < result["execution_date"]).all():
        raise ValueError("every signal_date must precede execution_date")
    if not (result["execution_date"] < result["label_end_date"]).all():
        raise ValueError("every label_end_date must follow execution_date")
    result["forward_return"] = pd.to_numeric(
        result["forward_return"], errors="coerce"
    )
    if not np.isfinite(result["forward_return"]).all():
        raise ValueError("forward_return must be finite and complete")
    for factor in FACTOR_NAMES:
        result[factor] = pd.to_numeric(result[factor], errors="coerce").replace(
            [np.inf, -np.inf], np.nan
        )
    period_sizes = result.groupby("execution_date")["ticker"].nunique()
    if int(period_sizes.min()) < 5:
        raise ValueError("each execution period needs at least five stocks")
    timing = result.groupby("execution_date").agg(
        signal_dates=("signal_date", "nunique"),
        label_end_dates=("label_end_date", "nunique"),
        signal_date=("signal_date", "first"),
        label_end_date=("label_end_date", "first"),
    )
    if (timing[["signal_dates", "label_end_dates"]] != 1).any().any():
        raise ValueError("each execution period needs one signal_date and label_end_date")
    execution_dates = list(timing.index)
    execution_gaps = pd.Series(execution_dates).diff().dropna().dt.days
    if not execution_gaps.between(20, 45).all():
        raise ValueError("factor evidence requires monthly execution periods")
    for position, next_execution in enumerate(execution_dates[1:]):
        if timing.iloc[position]["label_end_date"] != next_execution:
            raise ValueError("label_end_date must equal the next execution_date")
    return result.sort_values(["execution_date", "ticker"]).reset_index(drop=True)


def _rank_factors(panel: pd.DataFrame) -> pd.DataFrame:
    ranked = panel.copy()
    for factor in FACTOR_NAMES:
        ranked[f"rank_{factor}"] = ranked.groupby("execution_date")[factor].rank(
            pct=True,
            method="average",
        )
        ranked[f"rank_{factor}"] = ranked[f"rank_{factor}"].fillna(0.5)
    return ranked


def _cross_sectional_rank_ic(group: pd.DataFrame, rank_column: str) -> float:
    forward_rank = group["forward_return"].rank(pct=True, method="average")
    if group[rank_column].nunique(dropna=True) < 2 or forward_rank.nunique() < 2:
        return float("nan")
    return group[rank_column].corr(forward_rank)


def _portfolio_periods(
    panel: pd.DataFrame,
    score_column: str,
    *,
    top_fraction: float,
    cost_rate: float,
) -> pd.DataFrame:
    rows = []
    previous_weights: dict[str, float] = {}
    for execution_date, group in panel.groupby("execution_date", sort=True):
        group = group.dropna(subset=[score_column, "forward_return"]).copy()
        count = max(1, int(math.ceil(len(group) * top_fraction)))
        ordered = group.sort_values(score_column, ascending=False)
        top = ordered.head(count)
        bottom = ordered.tail(count)
        current_weights = {ticker: 1.0 / count for ticker in top["ticker"]}
        names = set(previous_weights) | set(current_weights)
        turnover = 0.5 * sum(
            abs(current_weights.get(name, 0.0) - previous_weights.get(name, 0.0))
            for name in names
        )
        gross_return = float(top["forward_return"].mean())
        universe_return = float(group["forward_return"].mean())
        bottom_return = float(bottom["forward_return"].mean())
        rows.append(
            {
                "execution_date": pd.Timestamp(execution_date),
                "gross_top_return": gross_return,
                "net_top_return": gross_return - turnover * cost_rate,
                "universe_return": universe_return,
                "net_top_excess": gross_return - turnover * cost_rate - universe_return,
                "top_bottom_spread": gross_return - bottom_return,
                "turnover": turnover,
                "selected_count": count,
            }
        )
        previous_weights = current_weights
    return pd.DataFrame(rows)


def _compound(returns: pd.Series) -> float:
    if returns.empty:
        return 0.0
    return float((1.0 + returns.astype(float)).prod() - 1.0)


def _optional_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _moving_block_mean_ci(
    values: pd.Series,
    *,
    samples: int,
    seed: int,
    block_size: int = 3,
) -> tuple[float, float]:
    clean = values.dropna().to_numpy(dtype=float)
    if len(clean) < 2:
        return (float(clean[0]), float(clean[0])) if len(clean) else (0.0, 0.0)
    rng = np.random.default_rng(seed)
    block_size = max(1, min(block_size, len(clean)))
    starts = np.arange(len(clean))
    means = []
    for _ in range(samples):
        draw = []
        while len(draw) < len(clean):
            start = int(rng.choice(starts))
            draw.extend(clean[(start + offset) % len(clean)] for offset in range(block_size))
        means.append(float(np.mean(draw[: len(clean)])))
    return float(np.quantile(means, 0.025)), float(np.quantile(means, 0.975))


def _composite_score(
    panel: pd.DataFrame,
    weights: dict[str, float],
    excluded_factor: str | None = None,
) -> pd.Series:
    active = {
        factor: float(weight)
        for factor, weight in weights.items()
        if factor != excluded_factor and float(weight) > 0
    }
    total = sum(active.values())
    if total <= 0:
        raise ValueError("composite score needs at least one positive factor weight")
    score = pd.Series(0.0, index=panel.index)
    for factor, weight in active.items():
        score = score + panel[f"rank_{factor}"] * (weight / total)
    return score


def build_factor_evidence(
    panel: pd.DataFrame,
    prior_weights: dict[str, float],
    *,
    market_scope: str,
    applicable_indices: list[str],
    universe_id: str,
    round_trip_cost_bps: float,
    independent_holdout: bool,
    top_fraction: float = 0.20,
    bootstrap_samples: int = 2000,
    seed: int = 7,
) -> dict[str, Any]:
    """Evaluate all factors under one timing, return, cost, and ablation contract."""
    if market_scope not in {"us", "krx"}:
        raise ValueError("market_scope must be us or krx")
    if not applicable_indices or not all(
        isinstance(item, str) and item for item in applicable_indices
    ):
        raise ValueError("applicable_indices must contain non-empty strings")
    if not isinstance(universe_id, str) or not universe_id.strip():
        raise ValueError("universe_id must be a non-empty string")
    if round_trip_cost_bps < 0:
        raise ValueError("round_trip_cost_bps cannot be negative")
    if not 0 < top_fraction <= 0.5:
        raise ValueError("top_fraction must be in (0, 0.5]")
    if bootstrap_samples < 200:
        raise ValueError("bootstrap_samples must be at least 200")
    priors = policy._validate_priors(prior_weights)
    validated = validate_factor_panel(panel)
    ranked = _rank_factors(validated)
    cost_rate = round_trip_cost_bps / 10000.0

    ranked["composite_all"] = _composite_score(ranked, priors)
    full_periods = _portfolio_periods(
        ranked,
        "composite_all",
        top_fraction=top_fraction,
        cost_rate=cost_rate,
    )
    full_net_total = _compound(full_periods["net_top_return"])

    factors = {}
    for factor_index, factor in enumerate(FACTOR_NAMES):
        rank_column = f"rank_{factor}"
        period_ic = ranked.groupby("execution_date", sort=True).apply(
            lambda group: _cross_sectional_rank_ic(group, rank_column),
            include_groups=False,
        )
        valid_period_ic = period_ic.dropna()
        factor_periods = _portfolio_periods(
            ranked,
            rank_column,
            top_fraction=top_fraction,
            cost_rate=cost_rate,
        )
        without_column = f"composite_without_{factor}"
        ranked[without_column] = _composite_score(
            ranked,
            priors,
            excluded_factor=factor,
        )
        without_periods = _portfolio_periods(
            ranked,
            without_column,
            top_fraction=top_fraction,
            cost_rate=cost_rate,
        )
        ci_low, ci_high = _moving_block_mean_ci(
            period_ic,
            samples=bootstrap_samples,
            seed=seed + factor_index,
        )
        metrics = {
            "observations": int(ranked[factor].notna().sum()),
            "data_coverage": float(ranked[factor].notna().mean()),
            "oos_periods": int(len(valid_period_ic)),
            "mean_rank_ic": _optional_float(valid_period_ic.mean()),
            "median_rank_ic": _optional_float(valid_period_ic.median()),
            "rank_ic_ci_low": ci_low,
            "rank_ic_ci_high": ci_high,
            "positive_ic_rate": _optional_float((valid_period_ic > 0).mean()),
            "mean_top_bottom_spread": float(
                factor_periods["top_bottom_spread"].mean()
            ),
            "net_top_total_return": _compound(factor_periods["net_top_return"]),
            "universe_total_return": _compound(
                factor_periods["universe_return"]
            ),
            "net_top_vs_universe_total_return": (
                _compound(factor_periods["net_top_return"])
                - _compound(factor_periods["universe_return"])
            ),
            "average_turnover": float(factor_periods["turnover"].mean()),
            "ablation_net_total_return_delta": (
                full_net_total - _compound(without_periods["net_top_return"])
            ),
        }
        assessment = policy.assess_factor_evidence(
            metrics,
            point_in_time=True,
            independent_holdout=independent_holdout,
        )
        factors[factor] = {
            "metrics": metrics,
            "assessment": assessment,
        }

    return {
        "schema_version": policy.SCHEMA_VERSION,
        "factor_spec_id": policy.PREDICT_FACTOR_SPEC_ID,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "validation_start": validated["execution_date"].min().strftime("%Y-%m-%d"),
        "validation_end": validated["label_end_date"].max().strftime("%Y-%m-%d"),
        "applicability": {
            "market_scope": market_scope,
            "indices": sorted(set(applicable_indices)),
            "universe_id": universe_id,
        },
        "methodology": {
            "target": "next_rebalance_forward_return",
            "rebalance_frequency": "monthly",
            "cross_sectional_metric": "monthly_spearman_rank_ic",
            "portfolio_test": f"top_{top_fraction:.0%}_equal_weight",
            "ablation": "all_prior_factors_minus_one",
            "round_trip_cost_bps": round_trip_cost_bps,
            "bootstrap": "moving_block_over_execution_periods",
            "bootstrap_samples": bootstrap_samples,
        },
        "validity": {
            "point_in_time": True,
            "signal_before_execution": True,
            "execution_before_label_end": True,
            "independent_holdout": bool(independent_holdout),
        },
        "prior_weights": priors,
        "factors": factors,
    }


def _load_prior_weights(path: str | Path) -> dict[str, float]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("prior weights JSON must be an object")
    weights = payload.get("factor_weights", payload)
    if not isinstance(weights, dict):
        raise ValueError("prior weights JSON needs factor_weights or direct weights")
    return policy._validate_priors(weights)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build unified point-in-time OOS evidence for predict factors"
    )
    parser.add_argument("--factor-panel", required=True)
    parser.add_argument("--prior-weights-json", required=True)
    parser.add_argument("--market-scope", choices=["us", "krx"], required=True)
    parser.add_argument("--applicable-index", action="append", required=True)
    parser.add_argument("--universe-id", required=True)
    parser.add_argument("--round-trip-cost-bps", type=float, required=True)
    parser.add_argument("--top-fraction", type=float, default=0.20)
    parser.add_argument("--bootstrap-samples", type=int, default=2000)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument(
        "--point-in-time",
        action="store_true",
        help="Assert that every factor value was observable by signal_date",
    )
    parser.add_argument(
        "--independent-holdout",
        action="store_true",
        help="Declare that the range was frozen before results were inspected",
    )
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    if not args.point_in_time:
        parser.error("--point-in-time is required; current snapshots are not accepted")

    panel = pd.read_csv(args.factor_panel)
    result = build_factor_evidence(
        panel,
        _load_prior_weights(args.prior_weights_json),
        market_scope=args.market_scope,
        applicable_indices=args.applicable_index,
        universe_id=args.universe_id,
        round_trip_cost_bps=args.round_trip_cost_bps,
        independent_holdout=args.independent_holdout,
        top_fraction=args.top_fraction,
        bootstrap_samples=args.bootstrap_samples,
        seed=args.seed,
    )
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False),
        encoding="utf-8",
    )
    print(f"Factor evidence saved: {output_path}")


if __name__ == "__main__":
    main()
