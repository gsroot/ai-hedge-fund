#!/usr/bin/env python3
"""
Two-stage active-LLM news sentiment enrichment for predict results.

Stage 1 prepares recent-news classification tasks for the base ranking's top
candidate pool. The current skill LLM supplies classifications. Stage 2
validates those classifications and adds risk/explanation evidence. Ranking
contribution stays disabled unless a separate validation artifact passes every
semantic, predictive, and portfolio gate.
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
INVESTOR_ANALYSIS_SCRIPTS = (
    Path(__file__).resolve().parents[2] / "investor-analysis" / "scripts"
)
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from data_fetcher import get_company_news  # noqa: E402
from factor_evidence import (  # noqa: E402
    PREDICT_FACTOR_SPEC_ID,
    SCHEMA_VERSION as FACTOR_EVIDENCE_SCHEMA_VERSION,
    assess_factor_evidence,
)

if str(INVESTOR_ANALYSIS_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(INVESTOR_ANALYSIS_SCRIPTS))

from analyze_news_sentiment import (  # noqa: E402
    MAX_LLM_ARTICLES,
    classification_exclusion_reason,
    prepare_news_for_llm,
    validate_classifications,
)


DEFAULT_CANDIDATE_POOL = 60
DEFAULT_ARTICLE_LIMIT = 5
CLASSIFICATION_SCHEMA_VERSION = 2
CLASSIFIER_POLICY_ID = "news_event_v2"
FUNDAMENTAL_FACTOR_SHARE = 0.40
SENTIMENT_SCORE_MIN = 2.0
SENTIMENT_SCORE_MAX = 8.0
RANKING_POLICY_EVIDENCE_ONLY = "risk_and_explanation_only"
RANKING_POLICY_VALIDATED = "validated_signal"


def _load_json(path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON 객체가 필요합니다: {path}")
    return payload


def _write_json(path: str | Path, payload: dict[str, Any]) -> None:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _validate_predict_payload(payload: dict[str, Any]) -> tuple[str, list[dict[str, Any]]]:
    analysis_date = str(payload.get("analysis_date") or "")
    rankings = payload.get("rankings")
    if not analysis_date:
        raise ValueError("predict JSON에 analysis_date가 없습니다.")
    if not isinstance(rankings, list) or not rankings:
        raise ValueError("predict JSON에 rankings가 없습니다.")
    return analysis_date, rankings


def prepare_candidate_tasks(
    predict_payload: dict[str, Any],
    candidate_pool: int = DEFAULT_CANDIDATE_POOL,
    article_limit: int = DEFAULT_ARTICLE_LIMIT,
) -> dict[str, Any]:
    """Fetch news and create active-skill-LLM tasks for top-ranked candidates."""
    analysis_date, rankings = _validate_predict_payload(predict_payload)
    if candidate_pool <= 0:
        raise ValueError("candidate_pool은 1 이상이어야 합니다.")
    if not 1 <= article_limit <= MAX_LLM_ARTICLES:
        raise ValueError(f"article_limit은 1~{MAX_LLM_ARTICLES}이어야 합니다.")

    selected = rankings[: min(candidate_pool, len(rankings))]
    tasks = []
    no_news_tickers = []
    duplicates_removed = 0

    for row in selected:
        ticker = str(row.get("ticker") or "").strip()
        if not ticker:
            continue
        news_items = get_company_news(ticker, analysis_date, limit=20)
        prepared = prepare_news_for_llm(
            {"company_news": news_items},
            ticker,
            limit=article_limit,
        )
        if not prepared["articles"]:
            no_news_tickers.append(ticker)
            continue
        duplicates_removed += int(prepared.get("duplicates_removed", 0))
        tasks.append(
            {
                **prepared,
                "base_rank": row.get("rank"),
                "company_name": row.get("company_name") or ticker,
            }
        )

    return {
        "schema_version": CLASSIFICATION_SCHEMA_VERSION,
        "classifier_policy_id": CLASSIFIER_POLICY_ID,
        "analysis_date": analysis_date,
        "index": predict_payload.get("index") or "custom",
        "source": "predict_top_candidate_news",
        "candidate_pool": len(selected),
        "article_limit": article_limit,
        "duplicates_removed": duplicates_removed,
        "tasks": tasks,
        "no_news_tickers": no_news_tickers,
        "classification_contract": {
            "schema_version": CLASSIFICATION_SCHEMA_VERSION,
            "classifier_policy_id": CLASSIFIER_POLICY_ID,
            "source": "active_skill_llm",
            "analysis_date": analysis_date,
            "results": [
                {
                    "ticker": "string",
                    "classifications": [
                        {
                            "article_index": "integer",
                            "relevance": "relevant|unrelated|ambiguous",
                            "event_type": "earnings_surprise|guidance|contract|financing_dilution|capital_return|legal_regulatory|product_partnership|management|market_price_recap|routine_disclosure|macro_industry|other",
                            "sentiment": "positive|negative|neutral",
                            "surprise": "positive|negative|none|unknown",
                            "impact_horizon": "intraday|short|medium|long|none",
                            "confidence": "number 0-100",
                            "abstain": "boolean",
                            "reasoning": "string",
                        }
                    ],
                }
            ],
        },
    }


def _classification_map(
    payload: dict[str, Any],
    analysis_date: str,
) -> dict[str, list[dict[str, Any]]]:
    if payload.get("schema_version") != CLASSIFICATION_SCHEMA_VERSION:
        raise ValueError(
            f"분류 JSON schema_version은 {CLASSIFICATION_SCHEMA_VERSION}이어야 합니다."
        )
    if payload.get("classifier_policy_id") != CLASSIFIER_POLICY_ID:
        raise ValueError(
            f"분류 JSON classifier_policy_id는 {CLASSIFIER_POLICY_ID}이어야 합니다."
        )
    if payload.get("source") != "active_skill_llm":
        raise ValueError("분류 JSON source는 active_skill_llm이어야 합니다.")
    if payload.get("analysis_date") != analysis_date:
        raise ValueError("분류 JSON과 predict 기준일이 다릅니다.")

    results = payload.get("results")
    if not isinstance(results, list):
        raise ValueError("분류 JSON에 results 배열이 필요합니다.")

    mapped = {}
    for result in results:
        if not isinstance(result, dict):
            continue
        ticker = str(result.get("ticker") or "").strip()
        classifications = result.get("classifications")
        if not ticker or not isinstance(classifications, list):
            continue
        if ticker in mapped:
            raise ValueError(f"분류 JSON에 중복 ticker가 있습니다: {ticker}")
        mapped[ticker] = classifications
    return mapped


def _score_validated_classifications(
    validated: list[dict[str, Any]],
    requested_articles: int,
    analysis_date: str,
) -> dict[str, Any] | None:
    if requested_articles <= 0 or not validated:
        return None

    actionable = []
    excluded = []
    for item in validated:
        reason = classification_exclusion_reason(item)
        if reason:
            excluded.append({**item, "exclusion_reason": reason})
        else:
            actionable.append(item)

    direction = {"positive": 1.0, "negative": -1.0, "neutral": 0.0}
    confidence_sum = sum(item["confidence"] for item in actionable)
    weighted_direction = sum(
        direction[item["sentiment"]] * item["confidence"]
        for item in actionable
    )
    polarity = weighted_direction / confidence_sum if confidence_sum > 0 else 0.0
    coverage = len(validated) / requested_articles
    actionable_coverage = len(actionable) / requested_articles
    average_confidence = (
        confidence_sum / len(actionable) / 100.0 if actionable else 0.0
    )
    reliability = actionable_coverage * average_confidence
    score = 5.0 + 3.0 * polarity * reliability
    score = max(SENTIMENT_SCORE_MIN, min(SENTIMENT_SCORE_MAX, score))
    sentiment_distribution = {
        sentiment: sum(item["sentiment"] == sentiment for item in actionable)
        for sentiment in ("positive", "negative", "neutral")
    }
    exclusion_distribution: dict[str, int] = {}
    for item in excluded:
        reason = item["exclusion_reason"]
        exclusion_distribution[reason] = exclusion_distribution.get(reason, 0) + 1
    risk_flags = [
        {
            "article_index": item["article_index"],
            "event_type": item["event_type"],
            "impact_horizon": item["impact_horizon"],
            "confidence": item["confidence"],
            "headline": item["headline"],
            "reasoning": item["reasoning"],
        }
        for item in actionable
        if item["sentiment"] == "negative" and item["confidence"] >= 70
    ]

    return {
        "source": "active_skill_llm",
        "analysis_date": analysis_date,
        "score": round(score, 4),
        "polarity": round(polarity, 4),
        "coverage": round(coverage, 4),
        "actionable_coverage": round(actionable_coverage, 4),
        "average_confidence": round(average_confidence, 4),
        "reliability": round(reliability, 4),
        "classified_articles": len(validated),
        "actionable_articles": len(actionable),
        "excluded_articles": len(excluded),
        "requested_articles": requested_articles,
        "sentiment_distribution": sentiment_distribution,
        "exclusion_distribution": exclusion_distribution,
        "risk_flags": risk_flags,
        "actionable_evidence": actionable,
        "excluded_evidence": excluded,
        "evidence": validated,
    }


def _number(value: Any, default: float = float("-inf")) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def evaluate_ranking_validation_gate(
    validation_payload: dict[str, Any] | None,
    factor_weight_policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Require common factor evidence plus detailed news-specific evidence."""
    reasons = []
    payload = validation_payload or {}
    decision = payload.get("validation_decision") or {}
    gates = decision.get("gates") or {}
    semantic = gates.get("semantic") or {}
    predictive = gates.get("predictive") or {}
    portfolio = gates.get("portfolio") or {}

    factor_policy = factor_weight_policy or {}
    factor_validity = factor_policy.get("validity") or {}
    sentiment_factor = (factor_policy.get("factors") or {}).get("sentiment") or {}
    if factor_policy.get("schema_version") != FACTOR_EVIDENCE_SCHEMA_VERSION:
        reasons.append("factor_evidence_schema_version")
    if factor_policy.get("factor_spec_id") != PREDICT_FACTOR_SPEC_ID:
        reasons.append("factor_spec_mismatch")
    if factor_policy.get("mode") != "evidence_shrunk":
        reasons.append("factor_evidence_not_applied")
    if (
        factor_validity.get("signal_before_execution") is not True
        or factor_validity.get("execution_before_label_end") is not True
    ):
        reasons.append("factor_evidence_timing_invalid")
    sentiment_assessment = assess_factor_evidence(
        sentiment_factor.get("metrics") or {},
        point_in_time=factor_validity.get("point_in_time") is True,
        independent_holdout=factor_validity.get("independent_holdout") is True,
    )
    if sentiment_assessment["grade"] not in {"promising", "robust"}:
        reasons.append("sentiment_factor_evidence_below_promising")

    if payload.get("schema_version") != 2:
        reasons.append("validation_schema_version")
    if payload.get("classifier_policy_id") != CLASSIFIER_POLICY_ID:
        reasons.append("classifier_policy_mismatch")
    if decision.get("accuracy_validated") is not True:
        reasons.append("accuracy_not_validated")
    if decision.get("evidence_grade") != "strong":
        reasons.append("evidence_grade_not_strong")

    recalls = semantic.get("class_recalls") or {}
    if _number(semantic.get("gold_sample_size")) < 90:
        reasons.append("semantic_gold_sample_below_90")
    if _number(semantic.get("macro_f1")) < 0.70:
        reasons.append("semantic_macro_f1_below_0_70")
    if any(
        _number(recalls.get(label)) < 0.60
        for label in ("positive", "negative", "neutral")
    ):
        reasons.append("semantic_class_recall_below_0_60")

    if _number(predictive.get("directional_event_count")) < 50:
        reasons.append("predictive_directional_events_below_50")
    if _number(predictive.get("wilson_lower_bound")) < 0.50:
        reasons.append("predictive_wilson_lower_bound_below_0_50")
    if _number(predictive.get("positive_mean_abnormal_return")) <= 0:
        reasons.append("positive_abnormal_return_not_positive")
    if _number(predictive.get("negative_mean_abnormal_return"), float("inf")) >= 0:
        reasons.append("negative_abnormal_return_not_negative")
    if _number(predictive.get("long_short_abnormal_return")) <= 0:
        reasons.append("long_short_abnormal_return_not_positive")
    if predictive.get("beats_neutral_baseline_5d") is not True:
        reasons.append("does_not_beat_neutral_baseline_5d")
    if predictive.get("beats_neutral_baseline_20d") is not True:
        reasons.append("does_not_beat_neutral_baseline_20d")

    if _number(portfolio.get("independent_holdout_windows")) < 2:
        reasons.append("portfolio_holdout_windows_below_2")
    if _number(portfolio.get("net_excess_return_delta")) <= 0:
        reasons.append("portfolio_net_excess_return_not_improved")
    if _number(portfolio.get("sharpe_delta")) <= 0:
        reasons.append("portfolio_sharpe_not_improved")

    return {
        "passed": not reasons,
        "policy": (
            RANKING_POLICY_VALIDATED if not reasons else RANKING_POLICY_EVIDENCE_ONLY
        ),
        "classifier_policy_id": CLASSIFIER_POLICY_ID,
        "factor_spec_id": PREDICT_FACTOR_SPEC_ID,
        "sentiment_factor_evidence_grade": sentiment_assessment["grade"],
        "failure_reasons": reasons,
    }


def build_sentiment_overrides(
    task_payload: dict[str, Any],
    classification_payload: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    analysis_date = str(task_payload.get("analysis_date") or "")
    if not analysis_date:
        raise ValueError("뉴스 작업 JSON에 analysis_date가 없습니다.")
    classifications = _classification_map(classification_payload, analysis_date)

    overrides = {}
    seen_tasks = set()
    for task in task_payload.get("tasks", []):
        if not isinstance(task, dict):
            continue
        ticker = str(task.get("ticker") or "").strip()
        if not ticker:
            continue
        if ticker in seen_tasks:
            raise ValueError(f"뉴스 작업 JSON에 중복 ticker가 있습니다: {ticker}")
        seen_tasks.add(ticker)

        validated = validate_classifications(task, classifications.get(ticker, []))
        override = _score_validated_classifications(
            validated,
            requested_articles=len(task.get("articles", [])),
            analysis_date=analysis_date,
        )
        if override:
            overrides[ticker] = override

    return overrides


def _hybrid_fundamental_weight(row: dict[str, Any]) -> float:
    scores = row.get("investor_scores", {})
    buffett = float(scores.get("buffett", 0.0))
    graham = float(scores.get("graham", 0.0))
    druckenmiller = float(scores.get("druckenmiller", 0.0))
    if buffett >= 7 and graham >= 6:
        return 0.85
    if druckenmiller >= 7 and buffett < 5 and graham < 5:
        return 0.55
    return 0.70


def _signal_for_score(score: float) -> str:
    if score >= 8:
        return "strong_buy"
    if score >= 5:
        return "buy"
    if score >= 2:
        return "hold"
    if score >= 0:
        return "weak_sell"
    return "sell"


def _score_implied_return_pct(score: float) -> float:
    normalized = (score - 3) / 10
    mapped = max(-0.30, min(0.40, normalized * 0.35))
    return round(mapped * 100, 1)


def _enrich_row(
    base_row: dict[str, Any],
    override: dict[str, Any],
    strategy: str,
    sentiment_weight: float,
    ranking_gate: dict[str, Any],
) -> dict[str, Any]:
    row = copy.deepcopy(base_row)
    scores = row.setdefault("scores", {})
    old_sentiment = float(scores.get("sentiment", 5.0))
    new_sentiment = float(override["score"])
    ranking_contribution_applied = bool(ranking_gate["passed"])
    effective_weight = sentiment_weight if ranking_contribution_applied else 0.0
    factor_delta = (new_sentiment - old_sentiment) * effective_weight
    fundamental_delta = factor_delta * FUNDAMENTAL_FACTOR_SHARE

    if strategy == "fundamental":
        total_delta = fundamental_delta
    elif strategy == "hybrid":
        total_delta = fundamental_delta * _hybrid_fundamental_weight(row)
    elif strategy == "momentum":
        total_delta = 0.0
    else:
        raise ValueError(f"지원하지 않는 predict 전략입니다: {strategy}")

    if ranking_contribution_applied:
        scores["sentiment"] = round(new_sentiment, 2)
    if ranking_contribution_applied and scores.get("fundamental") is not None:
        scores["fundamental"] = round(
            float(scores["fundamental"]) + fundamental_delta,
            2,
        )

    if ranking_contribution_applied:
        new_total_score = round(float(row.get("total_score", 0.0)) + total_delta, 2)
        row["total_score"] = new_total_score
        row["signal"] = _signal_for_score(new_total_score)
        row["score_implied_return_pct"] = _score_implied_return_pct(new_total_score)

    polarity = float(override.get("polarity", 0.0))
    direction = "긍정" if polarity > 0.05 else ("부정" if polarity < -0.05 else "중립")
    if ranking_contribution_applied:
        llm_factors = [
            f"검증된 LLM 뉴스 심리 {direction} ({new_sentiment:.1f}/8)",
            (
                f"LLM 뉴스 actionable coverage "
                f"{override['actionable_coverage'] * 100:.0f}%, "
                f"confidence {override['average_confidence'] * 100:.0f}%"
            ),
        ]
        existing_factors = [
            factor
            for factor in row.get("factors", [])
            if "뉴스" not in str(factor) and "coverage" not in str(factor)
        ]
        row["factors"] = (llm_factors + existing_factors)[:5]
    row["sentiment_analysis"] = {
        **override,
        "base_keyword_score": old_sentiment,
        "ranking_policy": ranking_gate["policy"],
        "ranking_contribution_applied": ranking_contribution_applied,
        "base_factor_weight": sentiment_weight,
        "effective_factor_weight": effective_weight,
        "total_score_delta": round(total_delta, 4),
        "calibrated": False,
        "validated_for_ranking": ranking_contribution_applied,
        "accuracy_validated": ranking_contribution_applied,
    }
    return row


def apply_news_sentiment_enrichment(
    predict_payload: dict[str, Any],
    task_payload: dict[str, Any],
    classification_payload: dict[str, Any],
    validation_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    analysis_date, rankings = _validate_predict_payload(predict_payload)
    if task_payload.get("analysis_date") != analysis_date:
        raise ValueError("뉴스 작업 JSON과 predict 기준일이 다릅니다.")
    if task_payload.get("index") != (predict_payload.get("index") or "custom"):
        raise ValueError("뉴스 작업 JSON과 predict 인덱스가 다릅니다.")
    if task_payload.get("schema_version") != CLASSIFICATION_SCHEMA_VERSION:
        raise ValueError(
            f"뉴스 작업 JSON schema_version은 {CLASSIFICATION_SCHEMA_VERSION}이어야 합니다."
        )
    if task_payload.get("classifier_policy_id") != CLASSIFIER_POLICY_ID:
        raise ValueError(
            f"뉴스 작업 JSON classifier_policy_id는 {CLASSIFIER_POLICY_ID}이어야 합니다."
        )

    strategy = str(predict_payload.get("strategy") or "hybrid")
    if strategy == "momentum":
        raise ValueError("momentum 전략은 sentiment를 사용하지 않아 뉴스 보강 대상이 아닙니다.")

    factor_weights = predict_payload.get("factor_weights") or {}
    sentiment_weight = float(factor_weights.get("sentiment", 0.08))
    if not 0 <= sentiment_weight <= 1:
        raise ValueError("predict sentiment 가중치가 유효하지 않습니다.")

    overrides = build_sentiment_overrides(task_payload, classification_payload)
    if not overrides:
        raise ValueError("검증을 통과한 현재 LLM 뉴스 분류가 없습니다.")

    ranking_gate = evaluate_ranking_validation_gate(
        validation_payload,
        predict_payload.get("factor_weight_policy"),
    )
    enriched_rankings = []
    applied = []
    for base_row in rankings:
        ticker = str(base_row.get("ticker") or "")
        override = overrides.get(ticker)
        if override:
            enriched_rankings.append(
                _enrich_row(
                    base_row,
                    override,
                    strategy,
                    sentiment_weight,
                    ranking_gate,
                )
            )
            applied.append(ticker)
        else:
            enriched_rankings.append(copy.deepcopy(base_row))

    if ranking_gate["passed"]:
        enriched_rankings.sort(key=lambda row: row.get("total_score", 0.0), reverse=True)
        for rank, row in enumerate(enriched_rankings, start=1):
            row["rank"] = rank

    result = copy.deepcopy(predict_payload)
    result["rankings"] = enriched_rankings
    result["total_analyzed"] = len(enriched_rankings)
    methodology_suffix = (
        "validated active-skill-LLM news sentiment replacement"
        if ranking_gate["passed"]
        else "active-skill-LLM news risk/explanation annotations (no ranking contribution)"
    )
    result["methodology"] = (
        f"{predict_payload.get('methodology', 'Multi-factor analysis')} "
        f"+ {methodology_suffix}"
    )
    result["news_sentiment_policy"] = {
        "classifier_policy_id": CLASSIFIER_POLICY_ID,
        "ranking_policy": ranking_gate["policy"],
        "ranking_contribution_applied": ranking_gate["passed"],
        "accuracy_validated": ranking_gate["passed"],
    }
    requested_articles = sum(
        override["requested_articles"] for override in overrides.values()
    )
    classified_articles = sum(
        override["classified_articles"] for override in overrides.values()
    )
    actionable_articles = sum(
        override["actionable_articles"] for override in overrides.values()
    )
    risk_flag_count = sum(len(override["risk_flags"]) for override in overrides.values())
    result["news_sentiment_enrichment"] = {
        "applied": True,
        "source": "active_skill_llm",
        "analysis_date": analysis_date,
        "candidate_pool": task_payload.get("candidate_pool"),
        "tasks_with_news": len(task_payload.get("tasks", [])),
        "enriched_tickers": len(applied),
        "applied_tickers": applied,
        "classified_articles": classified_articles,
        "actionable_articles": actionable_articles,
        "risk_flag_count": risk_flag_count,
        "requested_articles": requested_articles,
        "classification_coverage": (
            round(classified_articles / requested_articles, 4)
            if requested_articles
            else 0.0
        ),
        "ranking_policy": ranking_gate["policy"],
        "ranking_contribution_applied": ranking_gate["passed"],
        "base_sentiment_factor_weight": sentiment_weight,
        "effective_sentiment_factor_weight": (
            sentiment_weight if ranking_gate["passed"] else 0.0
        ),
        "validation_gate": ranking_gate,
        "calibrated": False,
        "validated_for_ranking": ranking_gate["passed"],
        "accuracy_validated": ranking_gate["passed"],
    }
    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Enrich top predict candidates with the active skill LLM's news sentiment"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    prepare_parser = subparsers.add_parser(
        "prepare",
        help="Prepare top-candidate news tasks for the current skill LLM",
    )
    prepare_parser.add_argument("--predict-json", required=True)
    prepare_parser.add_argument(
        "--candidate-pool",
        type=int,
        default=DEFAULT_CANDIDATE_POOL,
    )
    prepare_parser.add_argument(
        "--article-limit",
        type=int,
        default=DEFAULT_ARTICLE_LIMIT,
    )
    prepare_parser.add_argument("--output", required=True)

    apply_parser = subparsers.add_parser(
        "apply",
        help=(
            "Attach validated news evidence; affect ranking only when the optional "
            "validation artifact passes every gate"
        ),
    )
    apply_parser.add_argument("--predict-json", required=True)
    apply_parser.add_argument("--tasks-json", required=True)
    apply_parser.add_argument("--classifications-json", required=True)
    apply_parser.add_argument(
        "--validation-json",
        help="Independent semantic, predictive, and portfolio validation artifact",
    )
    apply_parser.add_argument("--output", required=True)

    args = parser.parse_args()
    predict_payload = _load_json(args.predict_json)

    if args.command == "prepare":
        output = prepare_candidate_tasks(
            predict_payload,
            candidate_pool=args.candidate_pool,
            article_limit=args.article_limit,
        )
    else:
        output = apply_news_sentiment_enrichment(
            predict_payload,
            _load_json(args.tasks_json),
            _load_json(args.classifications_json),
            _load_json(args.validation_json) if args.validation_json else None,
        )

    _write_json(args.output, output)
    print(f"결과 저장됨: {args.output}")


if __name__ == "__main__":
    main()
