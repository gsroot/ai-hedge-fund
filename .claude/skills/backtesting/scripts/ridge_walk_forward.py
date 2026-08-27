#!/usr/bin/env python3
"""Nested walk-forward ridge ranking on SEC point-in-time factor snapshots."""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd


SCRIPT_DIR = Path(__file__).resolve().parent


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


wf = _load_module("ridge_walk_forward_core", SCRIPT_DIR / "walk_forward.py")
mf = _load_module(
    "ridge_multifactor_core", SCRIPT_DIR / "multifactor_walk_forward.py"
)


FEATURES = (
    "value_factor",
    "quality_factor",
    "growth_factor",
    "rank_momentum_126",
    "rank_momentum_252",
    "rank_low_volatility",
    "fundamental_coverage",
)
ALPHAS = (0.1, 1.0, 10.0, 100.0)


@dataclass(frozen=True)
class RidgeConfig:
    alpha: float
    top_n: int
    weighting: str
    rebalance_months: int


def add_forward_returns(
    factor_panel: pd.DataFrame, opens: pd.DataFrame
) -> pd.DataFrame:
    """Attach next-rebalance returns for training labels only."""
    panel = factor_panel.copy()
    panel["execution_date"] = pd.to_datetime(panel["execution_date"])
    execution_dates = sorted(panel["execution_date"].unique())
    next_date = {
        pd.Timestamp(current): pd.Timestamp(following)
        for current, following in zip(execution_dates, execution_dates[1:])
    }
    forward_returns = []
    label_end_dates = []
    for row in panel.itertuples():
        current = pd.Timestamp(row.execution_date)
        following = next_date.get(current)
        label_end_dates.append(following)
        if following is None:
            forward_returns.append(np.nan)
            continue
        start_price = wf._valid_price(opens, current, row.ticker)
        end_price = wf._valid_price(opens, following, row.ticker)
        if start_price is None or end_price is None:
            forward_returns.append(np.nan)
        else:
            forward_returns.append(end_price / start_price - 1.0)
    panel["label_end_date"] = label_end_dates
    panel["forward_return"] = forward_returns
    panel["relative_forward_return"] = panel["forward_return"] - panel.groupby(
        "execution_date"
    )["forward_return"].transform("mean")
    # Cross-sectional winsorization is calculated within each historical month.
    panel["relative_forward_return"] = panel.groupby("execution_date")[
        "relative_forward_return"
    ].transform(
        lambda values: values.clip(values.quantile(0.05), values.quantile(0.95))
    )
    panel["fundamental_coverage"] = panel[
        ["value_factor", "quality_factor", "growth_factor"]
    ].notna().mean(axis=1)
    return panel


def _feature_matrix(frame: pd.DataFrame) -> np.ndarray:
    return frame[list(FEATURES)].astype(float).fillna(0.5).to_numpy()


def fit_ridge(frame: pd.DataFrame, alpha: float) -> dict:
    training = frame.dropna(subset=["relative_forward_return"])
    if len(training) < 100:
        raise ValueError("At least 100 labeled rows are required for ridge training")
    x = _feature_matrix(training)
    y = training["relative_forward_return"].to_numpy(dtype=float)
    mean = x.mean(axis=0)
    scale = x.std(axis=0, ddof=1)
    scale[scale < 1e-12] = 1.0
    standardized = (x - mean) / scale
    design = np.column_stack([np.ones(len(standardized)), standardized])
    penalty = np.eye(design.shape[1]) * alpha
    penalty[0, 0] = 0.0
    coefficients = np.linalg.solve(
        design.T @ design + penalty,
        design.T @ y,
    )
    return {
        "alpha": alpha,
        "mean": mean,
        "scale": scale,
        "coefficients": coefficients,
        "training_rows": len(training),
        "training_start": training["execution_date"].min(),
        "training_label_end": training["label_end_date"].max(),
    }


def predict_ridge(model: dict, frame: pd.DataFrame) -> pd.DataFrame:
    x = _feature_matrix(frame)
    standardized = (x - model["mean"]) / model["scale"]
    design = np.column_stack([np.ones(len(standardized)), standardized])
    result = frame.copy()
    result["prediction"] = design @ model["coefficients"]
    return result


def prediction_weight_schedule(
    predictions: pd.DataFrame,
    closes: pd.DataFrame,
    config: RidgeConfig,
) -> dict[pd.Timestamp, dict]:
    schedule = {}
    for execution_date, group in predictions.groupby("execution_date", sort=True):
        execution_date = pd.Timestamp(execution_date)
        if (execution_date.month - 1) % config.rebalance_months != 0:
            continue
        group = group.dropna(subset=["prediction"]).copy().set_index("ticker")
        selected = list(
            group.sort_values("prediction", ascending=False).index[: config.top_n]
        )
        signal_date = pd.Timestamp(group["signal_date"].iloc[0])
        dia = closes["DIA"].loc[:signal_date].dropna()
        market_regime = mf.assess_market_regime(
            dia,
            benchmark="DIA",
            as_of_date=signal_date,
        )
        gross_target = float(market_regime["target_equity_weight"])
        if config.weighting == "equal":
            weight = min(0.15, gross_target / config.top_n)
            weights = {ticker: weight for ticker in selected}
        else:
            raw_scores = {}
            minimum_prediction = float(group.loc[selected, "prediction"].min())
            for ticker in selected:
                volatility = group.at[ticker, "annualized_volatility"]
                if pd.isna(volatility):
                    continue
                shifted_score = float(group.at[ticker, "prediction"] - minimum_prediction) + 1e-6
                raw_scores[ticker] = shifted_score / max(float(volatility), 0.10)
            weights = mf._capped_allocation(raw_scores, gross_target)
        schedule[execution_date] = {
            "weights": weights,
            "detail": {
                "signal_date": signal_date.strftime("%Y-%m-%d"),
                "execution_date": execution_date.strftime("%Y-%m-%d"),
                "model": "ridge_cross_sectional_next_month_return",
                "configuration": {
                    "alpha": config.alpha,
                    "top_n": config.top_n,
                    "weighting": config.weighting,
                    "rebalance_months": config.rebalance_months,
                },
                "selected": selected,
                "predictions": {
                    ticker: float(group.at[ticker, "prediction"]) for ticker in selected
                },
                "target_invested_weight": sum(weights.values()),
                "market_regime": market_regime,
            },
        }
    return schedule


def equal_weight_schedule(
    factor_panel: pd.DataFrame,
    start_date: str,
    end_date: str,
    rebalance_months: int = 1,
) -> dict[pd.Timestamp, dict]:
    """Build a fixed, non-optimized historical-universe equal-weight baseline."""
    start = pd.Timestamp(start_date)
    end = pd.Timestamp(end_date)
    schedule = {}
    for execution_date, group in factor_panel.groupby("execution_date", sort=True):
        execution_date = pd.Timestamp(execution_date)
        if not start <= execution_date <= end:
            continue
        if (execution_date.month - 1) % rebalance_months != 0:
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


def select_inner_config(
    labeled_panel: pd.DataFrame,
    opens: pd.DataFrame,
    closes: pd.DataFrame,
    fold: dict,
    cost_rate: float,
) -> tuple[RidgeConfig, list[dict]]:
    train_start = pd.Timestamp(fold["train_start"])
    train_end = pd.Timestamp(fold["train_end"])
    validation_start = train_end - pd.DateOffset(years=1) + pd.Timedelta(days=1)
    inner_training = labeled_panel[
        (labeled_panel["execution_date"] >= train_start)
        & (labeled_panel["label_end_date"] < validation_start)
    ]
    validation = labeled_panel[
        (labeled_panel["execution_date"] >= validation_start)
        & (labeled_panel["label_end_date"] <= train_end)
    ]
    if inner_training.empty or validation.empty:
        raise ValueError(f"Insufficient nested training rows for fold {fold}")
    trials = []
    predictions_by_alpha = {}
    models = {}
    for alpha in ALPHAS:
        model = fit_ridge(inner_training, alpha)
        models[alpha] = model
        predictions_by_alpha[alpha] = predict_ridge(model, validation)
    for alpha in ALPHAS:
        for top_n in (8, 12, 20, 30):
            for weighting in ("equal", "score_inverse_vol"):
                for rebalance_months in (1, 3):
                    config = RidgeConfig(
                        alpha,
                        top_n,
                        weighting,
                        rebalance_months,
                    )
                    schedule = prediction_weight_schedule(
                        predictions_by_alpha[alpha], closes, config
                    )
                    simulation = wf.simulate_weight_schedule(
                        opens,
                        closes,
                        validation_start.strftime("%Y-%m-%d"),
                        train_end.strftime("%Y-%m-%d"),
                        cost_rate,
                        schedule,
                    )
                    metrics = wf.performance_metrics(
                        simulation["equity"], simulation["returns"]
                    )
                    trials.append(
                        {
                            "config": config,
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
    serializable = [
        {
            "configuration": {
                "alpha": trial["config"].alpha,
                "top_n": trial["config"].top_n,
                "weighting": trial["config"].weighting,
                "rebalance_months": trial["config"].rebalance_months,
            },
            "metrics": trial["metrics"],
            "turnover": trial["turnover"],
        }
        for trial in trials
    ]
    return best["config"], serializable


def _model_summary(model: dict) -> dict:
    coefficients = model["coefficients"]
    return {
        "alpha": model["alpha"],
        "training_rows": model["training_rows"],
        "training_start": pd.Timestamp(model["training_start"]).strftime("%Y-%m-%d"),
        "training_label_end": pd.Timestamp(model["training_label_end"]).strftime(
            "%Y-%m-%d"
        ),
        "intercept": float(coefficients[0]),
        "standardized_coefficients": {
            feature: float(value) for feature, value in zip(FEATURES, coefficients[1:])
        },
    }


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
    factor_panel = pd.read_csv(
        args.factor_panel,
        parse_dates=["execution_date", "signal_date", "latest_filed_date"],
    )
    opens, closes, adjusted_hash = wf.load_price_cache(Path(args.adjusted_price_cache))
    labeled = add_forward_returns(factor_panel, opens)
    labeled.to_csv(
        output_dir / "ridge_labeled_factor_panel.csv", index=False, date_format="%Y-%m-%d"
    )
    folds = wf.make_folds(args.start_oos, args.end_oos, args.train_years)
    cost_rate = (args.commission_bps + args.slippage_bps) / 10000.0
    selected_schedule = {}
    fold_results = []
    for fold in folds:
        config, inner_trials = select_inner_config(
            labeled, opens, closes, fold, cost_rate
        )
        train_end = pd.Timestamp(fold["train_end"])
        full_training = labeled[
            (labeled["execution_date"] >= pd.Timestamp(fold["train_start"]))
            & (labeled["label_end_date"] <= train_end)
        ]
        model = fit_ridge(full_training, config.alpha)
        if pd.Timestamp(model["training_label_end"]) > train_end:
            raise AssertionError("ridge training used a label after the fold cutoff")
        test_rows = labeled[
            (labeled["execution_date"] >= pd.Timestamp(fold["test_start"]))
            & (labeled["execution_date"] <= pd.Timestamp(fold["test_end"]))
        ]
        predictions = predict_ridge(model, test_rows)
        test_schedule = prediction_weight_schedule(predictions, closes, config)
        test = wf.simulate_weight_schedule(
            opens,
            closes,
            fold["test_start"],
            fold["test_end"],
            cost_rate,
            test_schedule,
        )
        selected_schedule.update(test_schedule)
        fold_results.append(
            {
                **fold,
                "selected_configuration": {
                    "alpha": config.alpha,
                    "top_n": config.top_n,
                    "weighting": config.weighting,
                    "rebalance_months": config.rebalance_months,
                },
                "model": _model_summary(model),
                "inner_validation_trials": inner_trials,
                "test_metrics_reset_at_fold_start": wf.performance_metrics(
                    test["equity"], test["returns"]
                ),
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
        equal_weight_schedule(
            factor_panel, args.start_oos, args.end_oos, rebalance_months=1
        ),
    )
    strategy_metrics = wf.performance_metrics(oos["equity"], oos["returns"])
    benchmark_metrics = wf.performance_metrics(
        benchmark["equity"], benchmark["returns"]
    )
    equal_weight_metrics = wf.performance_metrics(
        equal_weight["equity"], equal_weight["returns"]
    )
    universe_coverage = mf.universe_coverage_summary(factor_panel)
    paired_dia = wf.paired_block_bootstrap_cagr_difference(
        oos["returns"],
        benchmark["returns"],
        samples=args.bootstrap_samples,
    )
    paired_equal_weight = wf.paired_block_bootstrap_cagr_difference(
        oos["returns"],
        equal_weight["returns"],
        samples=args.bootstrap_samples,
    )
    evidence_assessment = mf.assess_evidence(
        strategy_metrics,
        benchmark_metrics,
        equal_weight_metrics,
        paired_dia,
        paired_equal_weight,
        universe_coverage,
        bool(args.independent_holdout),
        int(oos["returns"].dropna().shape[0]),
    )
    result = {
        "experiment": {
            "name": "nested_ridge_sec_point_in_time_walk_forward",
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "oos_start": args.start_oos,
            "oos_end": args.end_oos,
            "outer_training_years": args.train_years,
            "inner_validation": "last year of each outer training window",
            "features": list(FEATURES),
            "target": "next-month stock return minus cross-sectional mean",
            "alphas": list(ALPHAS),
            "signal_timing": "SEC filed <= prior close; trade next open",
            "commission_bps": args.commission_bps,
            "slippage_bps": args.slippage_bps,
            "max_name_weight": 0.15,
            "research_iteration": (
                "independent_holdout" if args.independent_holdout else "development"
            ),
        },
        "data": {
            "factor_panel": str(Path(args.factor_panel).resolve()),
            "adjusted_price_cache": str(Path(args.adjusted_price_cache).resolve()),
            "adjusted_price_cache_sha256": adjusted_hash,
            "labeled_rows": int(labeled["relative_forward_return"].notna().sum()),
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
        "folds": fold_results,
        "validity": {
            "nested_validation_used": True,
            "training_labels_end_before_oos": True,
            "non_overlapping_outer_oos_folds": True,
            "historical_membership_used": True,
            "sec_filed_date_enforced_by_factor_panel": True,
            "investment_claim": "research evidence only; not a highest-return guarantee",
        },
    }
    result_path = output_dir / "ridge_walk_forward_results.json"
    result_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, default=_json_default),
        encoding="utf-8",
    )
    equity = pd.concat([oos["equity"], benchmark["equity"]], axis=1)
    equity["strategy_return"] = oos["returns"]
    equity["benchmark_return"] = benchmark["returns"]
    equity.to_csv(output_dir / "ridge_oos_equity.csv", index_label="date")
    pd.DataFrame(oos["rebalances"]).to_csv(
        output_dir / "ridge_oos_rebalances.csv", index=False
    )
    return result


def print_summary(result: dict) -> None:
    strategy = result["oos_strategy"]["metrics"]
    benchmark = result["benchmark_dia"]["metrics"]
    print("\nNested ridge point-in-time walk-forward")
    print(
        f"Strategy CAGR {strategy['cagr']:.2%}, total {strategy['total_return']:.2%}, "
        f"Sharpe {strategy['sharpe_ratio']:.2f}, MDD {strategy['max_drawdown']:.2%}"
    )
    print(
        f"DIA      CAGR {benchmark['cagr']:.2%}, total {benchmark['total_return']:.2%}, "
        f"Sharpe {benchmark['sharpe_ratio']:.2f}, MDD {benchmark['max_drawdown']:.2%}"
    )
    print(f"CAGR difference {result['comparison']['cagr_difference']:+.2%}")
    evidence = result["evidence_assessment"]
    print(f"Evidence grade: {evidence['grade']} ({evidence['interpretation']})")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Nested ridge SEC point-in-time walk-forward validation"
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
    parser.add_argument(
        "--factor-panel",
        default="artifacts/walk_forward/dow_multifactor_2018_2025/point_in_time_factor_panel.csv",
    )
    parser.add_argument(
        "--adjusted-price-cache",
        default="artifacts/walk_forward/dow_momentum_2018_2025/adjusted_ohlc.csv",
    )
    parser.add_argument(
        "--output-dir", default="artifacts/walk_forward/dow_multifactor_2018_2025"
    )
    args = parser.parse_args()
    if args.train_years < 3:
        parser.error("nested validation requires train-years >= 3")
    if args.commission_bps < 0 or args.slippage_bps < 0:
        parser.error("costs cannot be negative")
    if args.bootstrap_samples < 100:
        parser.error("bootstrap-samples must be at least 100")
    Path(args.output_dir).mkdir(parents=True, exist_ok=True)
    result = run(args)
    print_summary(result)


if __name__ == "__main__":
    main()
