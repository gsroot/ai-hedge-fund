#!/usr/bin/env python3
"""
Two-stage active-LLM news sentiment enrichment for predict results.

Stage 1 prepares recent-news classification tasks for the base ranking's top
candidate pool. The current skill LLM supplies classifications. Stage 2
validates those classifications and replaces the existing sentiment factor
contribution without rerunning or perturbing other factors.
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

if str(INVESTOR_ANALYSIS_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(INVESTOR_ANALYSIS_SCRIPTS))

from analyze_news_sentiment import (  # noqa: E402
    MAX_LLM_ARTICLES,
    prepare_news_for_llm,
    validate_classifications,
)


DEFAULT_CANDIDATE_POOL = 60
DEFAULT_ARTICLE_LIMIT = 5
FUNDAMENTAL_FACTOR_SHARE = 0.40
SENTIMENT_SCORE_MIN = 2.0
SENTIMENT_SCORE_MAX = 8.0


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
        tasks.append(
            {
                **prepared,
                "base_rank": row.get("rank"),
                "company_name": row.get("company_name") or ticker,
            }
        )

    return {
        "schema_version": 1,
        "analysis_date": analysis_date,
        "index": predict_payload.get("index") or "custom",
        "source": "predict_top_candidate_news",
        "candidate_pool": len(selected),
        "article_limit": article_limit,
        "tasks": tasks,
        "no_news_tickers": no_news_tickers,
        "classification_contract": {
            "source": "active_skill_llm",
            "analysis_date": analysis_date,
            "results": [
                {
                    "ticker": "string",
                    "classifications": [
                        {
                            "article_index": "integer",
                            "sentiment": "positive|negative|neutral",
                            "confidence": "number 0-100",
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

    direction = {"positive": 1.0, "negative": -1.0, "neutral": 0.0}
    confidence_sum = sum(item["confidence"] for item in validated)
    weighted_direction = sum(
        direction[item["sentiment"]] * item["confidence"]
        for item in validated
    )
    polarity = weighted_direction / confidence_sum if confidence_sum > 0 else 0.0
    coverage = len(validated) / requested_articles
    average_confidence = confidence_sum / len(validated) / 100.0
    reliability = coverage * average_confidence
    score = 5.0 + 3.0 * polarity * reliability
    score = max(SENTIMENT_SCORE_MIN, min(SENTIMENT_SCORE_MAX, score))

    return {
        "source": "active_skill_llm",
        "analysis_date": analysis_date,
        "score": round(score, 4),
        "polarity": round(polarity, 4),
        "coverage": round(coverage, 4),
        "average_confidence": round(average_confidence, 4),
        "reliability": round(reliability, 4),
        "classified_articles": len(validated),
        "requested_articles": requested_articles,
        "evidence": validated,
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
) -> dict[str, Any]:
    row = copy.deepcopy(base_row)
    scores = row.setdefault("scores", {})
    old_sentiment = float(scores.get("sentiment", 5.0))
    new_sentiment = float(override["score"])
    factor_delta = (new_sentiment - old_sentiment) * sentiment_weight
    fundamental_delta = factor_delta * FUNDAMENTAL_FACTOR_SHARE

    if strategy == "fundamental":
        total_delta = fundamental_delta
    elif strategy == "hybrid":
        total_delta = fundamental_delta * _hybrid_fundamental_weight(row)
    elif strategy == "momentum":
        total_delta = 0.0
    else:
        raise ValueError(f"지원하지 않는 predict 전략입니다: {strategy}")

    scores["sentiment"] = round(new_sentiment, 2)
    if scores.get("fundamental") is not None:
        scores["fundamental"] = round(
            float(scores["fundamental"]) + fundamental_delta,
            2,
        )

    new_total_score = round(float(row.get("total_score", 0.0)) + total_delta, 2)
    row["total_score"] = new_total_score
    row["signal"] = _signal_for_score(new_total_score)
    row["score_implied_return_pct"] = _score_implied_return_pct(new_total_score)

    polarity = float(override.get("polarity", 0.0))
    direction = "긍정" if polarity > 0.05 else ("부정" if polarity < -0.05 else "중립")
    llm_factors = [
        f"현재 LLM 뉴스 심리 {direction} ({new_sentiment:.1f}/8)",
        (
            f"LLM 뉴스 coverage {override['coverage'] * 100:.0f}%, "
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
        "factor_weight": sentiment_weight,
        "total_score_delta": round(total_delta, 4),
        "calibrated": False,
    }
    return row


def apply_news_sentiment_enrichment(
    predict_payload: dict[str, Any],
    task_payload: dict[str, Any],
    classification_payload: dict[str, Any],
) -> dict[str, Any]:
    analysis_date, rankings = _validate_predict_payload(predict_payload)
    if task_payload.get("analysis_date") != analysis_date:
        raise ValueError("뉴스 작업 JSON과 predict 기준일이 다릅니다.")
    if task_payload.get("index") != (predict_payload.get("index") or "custom"):
        raise ValueError("뉴스 작업 JSON과 predict 인덱스가 다릅니다.")

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

    enriched_rankings = []
    applied = []
    for base_row in rankings:
        ticker = str(base_row.get("ticker") or "")
        override = overrides.get(ticker)
        if override:
            enriched_rankings.append(
                _enrich_row(base_row, override, strategy, sentiment_weight)
            )
            applied.append(ticker)
        else:
            enriched_rankings.append(copy.deepcopy(base_row))

    enriched_rankings.sort(key=lambda row: row.get("total_score", 0.0), reverse=True)
    for rank, row in enumerate(enriched_rankings, start=1):
        row["rank"] = rank

    result = copy.deepcopy(predict_payload)
    result["rankings"] = enriched_rankings
    result["total_analyzed"] = len(enriched_rankings)
    result["methodology"] = (
        f"{predict_payload.get('methodology', 'Multi-factor analysis')} "
        "+ bounded active-skill-LLM news sentiment replacement"
    )
    requested_articles = sum(
        override["requested_articles"] for override in overrides.values()
    )
    classified_articles = sum(
        override["classified_articles"] for override in overrides.values()
    )
    result["news_sentiment_enrichment"] = {
        "applied": True,
        "source": "active_skill_llm",
        "analysis_date": analysis_date,
        "candidate_pool": task_payload.get("candidate_pool"),
        "tasks_with_news": len(task_payload.get("tasks", [])),
        "enriched_tickers": len(applied),
        "applied_tickers": applied,
        "classified_articles": classified_articles,
        "requested_articles": requested_articles,
        "classification_coverage": (
            round(classified_articles / requested_articles, 4)
            if requested_articles
            else 0.0
        ),
        "sentiment_score_range": [
            SENTIMENT_SCORE_MIN,
            SENTIMENT_SCORE_MAX,
        ],
        "sentiment_factor_weight": sentiment_weight,
        "calibrated": False,
        "accuracy_validated": False,
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
        help="Validate classifications and replace the existing sentiment factor",
    )
    apply_parser.add_argument("--predict-json", required=True)
    apply_parser.add_argument("--tasks-json", required=True)
    apply_parser.add_argument("--classifications-json", required=True)
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
        )

    _write_json(args.output, output)
    print(f"결과 저장됨: {args.output}")


if __name__ == "__main__":
    main()
