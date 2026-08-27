#!/usr/bin/env python3
"""Validate and apply point-in-time factor evidence to predict priors."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 1
PREDICT_FACTOR_SPEC_ID = "predict_factor_v1"
FACTOR_NAMES = (
    "value",
    "growth",
    "quality",
    "momentum",
    "safety",
    "sentiment",
    "insider",
)
EVIDENCE_MULTIPLIERS = {
    "contradicted": 0.0,
    "weak": 0.35,
    "unvalidated": 0.50,
    "preliminary": 0.65,
    "promising": 0.85,
    "robust": 1.0,
}


def _number(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if number != number or number in (float("inf"), float("-inf")):
        return default
    return number


def assess_factor_evidence(
    metrics: dict[str, Any],
    *,
    point_in_time: bool,
    independent_holdout: bool,
) -> dict[str, Any]:
    """Map common OOS metrics to a conservative, precommitted shrinkage grade."""
    periods = int(_number(metrics.get("oos_periods")))
    coverage = _number(metrics.get("data_coverage"))
    mean_ic = _number(metrics.get("mean_rank_ic"))
    ic_ci_low = _number(metrics.get("rank_ic_ci_low"), -1.0)
    positive_rate = _number(metrics.get("positive_ic_rate"))
    net_excess = _number(metrics.get("net_top_vs_universe_total_return"))
    ablation = _number(metrics.get("ablation_net_total_return_delta"))

    checks = {
        "point_in_time": bool(point_in_time),
        "minimum_12_oos_periods": periods >= 12,
        "minimum_36_oos_periods": periods >= 36,
        "data_coverage_at_least_80pct": coverage >= 0.80,
        "data_coverage_at_least_90pct": coverage >= 0.90,
        "mean_rank_ic_positive": mean_ic > 0,
        "rank_ic_ci_low_positive": ic_ci_low > 0,
        "positive_ic_rate_at_least_50pct": positive_rate >= 0.50,
        "positive_ic_rate_at_least_55pct": positive_rate >= 0.55,
        "net_top_vs_universe_positive": net_excess > 0,
        "ablation_delta_positive": ablation > 0,
        "independent_holdout": bool(independent_holdout),
    }

    contradicted = (
        periods >= 12
        and mean_ic <= 0
        and net_excess <= 0
        and ablation <= 0
    )
    robust = all(
        checks[key]
        for key in (
            "point_in_time",
            "minimum_36_oos_periods",
            "data_coverage_at_least_90pct",
            "mean_rank_ic_positive",
            "rank_ic_ci_low_positive",
            "positive_ic_rate_at_least_55pct",
            "net_top_vs_universe_positive",
            "ablation_delta_positive",
            "independent_holdout",
        )
    )
    promising = all(
        checks[key]
        for key in (
            "point_in_time",
            "minimum_12_oos_periods",
            "data_coverage_at_least_90pct",
            "mean_rank_ic_positive",
            "positive_ic_rate_at_least_50pct",
            "net_top_vs_universe_positive",
            "ablation_delta_positive",
            "independent_holdout",
        )
    )
    preliminary = all(
        checks[key]
        for key in (
            "point_in_time",
            "minimum_12_oos_periods",
            "data_coverage_at_least_80pct",
            "mean_rank_ic_positive",
            "net_top_vs_universe_positive",
        )
    )

    if robust:
        grade = "robust"
    elif promising:
        grade = "promising"
    elif preliminary:
        grade = "preliminary"
    elif contradicted:
        grade = "contradicted"
    else:
        grade = "weak"
    return {
        "grade": grade,
        "multiplier": EVIDENCE_MULTIPLIERS[grade],
        "checks": checks,
        "policy": "multiply_prior_by_evidence_then_normalize_fixed_factor_budget",
    }


def _normalize_weights(
    priors: dict[str, float],
    multipliers: dict[str, float],
) -> tuple[dict[str, float], str | None]:
    target_total = sum(priors.values())
    raw = {
        factor: priors[factor] * multipliers[factor]
        for factor in FACTOR_NAMES
    }
    raw_total = sum(raw.values())
    if raw_total <= 0:
        return dict(priors), "all_factors_contradicted_fallback_to_prior_relative_weights"
    return {
        factor: raw[factor] / raw_total * target_total
        for factor in FACTOR_NAMES
    }, None


def _validate_priors(prior_weights: dict[str, Any]) -> dict[str, float]:
    if set(prior_weights) != set(FACTOR_NAMES):
        raise ValueError(f"prior factor keys must be exactly {list(FACTOR_NAMES)}")
    priors = {factor: _number(prior_weights[factor], -1.0) for factor in FACTOR_NAMES}
    if any(value < 0 for value in priors.values()) or sum(priors.values()) <= 0:
        raise ValueError("prior factor weights must be non-negative with a positive sum")
    return priors


def default_factor_weight_policy(
    prior_weights: dict[str, Any],
) -> dict[str, Any]:
    """Keep prior relative weights while marking every factor unvalidated."""
    priors = _validate_priors(prior_weights)
    multipliers = {
        factor: EVIDENCE_MULTIPLIERS["unvalidated"] for factor in FACTOR_NAMES
    }
    effective, fallback = _normalize_weights(priors, multipliers)
    return {
        "schema_version": SCHEMA_VERSION,
        "factor_spec_id": PREDICT_FACTOR_SPEC_ID,
        "mode": "prior_only",
        "source": None,
        "prior_weights": priors,
        "effective_weights": effective,
        "factors": {
            factor: {
                "grade": "unvalidated",
                "multiplier": multipliers[factor],
                "metrics": None,
            }
            for factor in FACTOR_NAMES
        },
        "fallback_reason": fallback,
    }


def build_factor_weight_policy(
    prior_weights: dict[str, Any],
    evidence_payload: dict[str, Any],
    *,
    market_scope: str,
    index: str,
    analysis_date: str,
    source: str | None = None,
) -> dict[str, Any]:
    """Validate an evidence artifact and shrink all factor priors consistently."""
    priors = _validate_priors(prior_weights)
    if evidence_payload.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"factor evidence schema_version must be {SCHEMA_VERSION}")
    if evidence_payload.get("factor_spec_id") != PREDICT_FACTOR_SPEC_ID:
        raise ValueError(
            f"factor evidence factor_spec_id must be {PREDICT_FACTOR_SPEC_ID}"
        )
    applicability = evidence_payload.get("applicability") or {}
    if not isinstance(applicability, dict):
        raise ValueError("factor evidence applicability must be an object")
    if applicability.get("market_scope") != market_scope:
        raise ValueError("factor evidence market_scope does not match predict input")
    applicable_indices = applicability.get("indices") or []
    if not isinstance(applicable_indices, list) or not all(
        isinstance(item, str) and item for item in applicable_indices
    ):
        raise ValueError("factor evidence applicability.indices must be a string list")
    if index != "custom" and index not in applicable_indices:
        raise ValueError("factor evidence is not approved for this index")
    validation_end = str(evidence_payload.get("validation_end") or "")
    try:
        validation_end_date = datetime.strptime(validation_end, "%Y-%m-%d").date()
        analysis_date_value = datetime.strptime(analysis_date, "%Y-%m-%d").date()
    except ValueError as exc:
        raise ValueError("factor evidence dates must use YYYY-MM-DD") from exc
    if validation_end_date >= analysis_date_value:
        raise ValueError("factor evidence validation_end must precede analysis_date")
    validity = evidence_payload.get("validity") or {}
    if not isinstance(validity, dict):
        raise ValueError("factor evidence validity must be an object")
    if validity.get("point_in_time") is not True:
        raise ValueError("factor evidence must enforce point-in-time data")
    if validity.get("signal_before_execution") is not True:
        raise ValueError("factor evidence must enforce signal_before_execution")
    if validity.get("execution_before_label_end") is not True:
        raise ValueError("factor evidence must enforce execution_before_label_end")

    independent_holdout = validity.get("independent_holdout") is True
    evidence_factors = evidence_payload.get("factors") or {}
    if not isinstance(evidence_factors, dict):
        raise ValueError("factor evidence factors must be an object")
    unknown_factors = sorted(set(evidence_factors) - set(FACTOR_NAMES))
    if unknown_factors:
        raise ValueError(f"factor evidence has unknown factors: {unknown_factors}")
    decisions = {}
    multipliers = {}
    for factor in FACTOR_NAMES:
        factor_payload = evidence_factors.get(factor)
        if not isinstance(factor_payload, dict):
            decision = {
                "grade": "unvalidated",
                "multiplier": EVIDENCE_MULTIPLIERS["unvalidated"],
                "checks": {},
                "policy": "missing_factor_evidence_uses_unvalidated_prior_multiplier",
            }
            metrics = None
        else:
            metrics = factor_payload.get("metrics") or {}
            decision = assess_factor_evidence(
                metrics,
                point_in_time=True,
                independent_holdout=independent_holdout,
            )
        decisions[factor] = {
            **decision,
            "metrics": metrics,
        }
        multipliers[factor] = float(decision["multiplier"])

    effective, fallback = _normalize_weights(priors, multipliers)
    return {
        "schema_version": SCHEMA_VERSION,
        "factor_spec_id": PREDICT_FACTOR_SPEC_ID,
        "mode": "evidence_shrunk",
        "source": source,
        "validation_end": validation_end,
        "applicability": applicability,
        "validity": validity,
        "prior_weights": priors,
        "effective_weights": effective,
        "factors": decisions,
        "fallback_reason": fallback,
    }


def load_factor_weight_policy(
    prior_weights: dict[str, Any],
    evidence_path: str | Path | None,
    *,
    market_scope: str,
    index: str,
    analysis_date: str,
) -> dict[str, Any]:
    if evidence_path is None:
        return default_factor_weight_policy(prior_weights)
    path = Path(evidence_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("factor evidence JSON must be an object")
    return build_factor_weight_policy(
        prior_weights,
        payload,
        market_scope=market_scope,
        index=index,
        analysis_date=analysis_date,
        source=str(path.resolve()),
    )
