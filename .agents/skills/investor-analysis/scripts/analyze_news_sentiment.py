#!/usr/bin/env python3
"""
뉴스 심리 분석 보조 스크립트.

별도 모델 API를 호출하지 않는다. 스킬을 실행 중인 현재 LLM이
prepare_news_for_llm()의 기사를 분류하고, 이 모듈은 그 결과를 검증·집계한다.
"""
import argparse
import json
import sys
from pathlib import Path
from typing import Any


VALID_SENTIMENTS = {"positive", "negative", "neutral"}
MAX_RECENT_ARTICLES = 10
MAX_LLM_ARTICLES = 5


def _headline(news: dict[str, Any]) -> str:
    return str(news.get("summary") or news.get("title") or "").strip()


def prepare_news_for_llm(
    news_data: dict[str, Any],
    ticker: str,
    limit: int = MAX_LLM_ARTICLES,
) -> dict[str, Any]:
    """현재 스킬 LLM이 분류할 기사와 출력 계약을 만든다."""
    company_news = news_data.get("company_news", [])
    articles = []
    for article_index, news in enumerate(company_news[:MAX_RECENT_ARTICLES]):
        if news.get("sentiment") is not None:
            continue
        headline = _headline(news)
        if not headline:
            continue
        articles.append(
            {
                "article_index": article_index,
                "headline": headline,
                "date": news.get("date"),
                "publisher": news.get("publisher"),
                "link": news.get("link"),
                "content_type": news.get("content_type"),
            }
        )
        if len(articles) >= max(0, min(limit, MAX_LLM_ARTICLES)):
            break

    return {
        "ticker": ticker,
        "classification_source": "active_skill_llm",
        "instruction": (
            "현재 스킬을 실행 중인 LLM이 각 기사가 해당 종목에 미치는 심리를 "
            "positive, negative, neutral 중 하나로 분류하고 confidence 0-100과 "
            "간단한 reasoning을 반환한다. 외부 모델 API를 호출하거나 모델을 지정하지 않는다."
        ),
        "articles": articles,
        "response_schema": {
            "classifications": [
                {
                    "article_index": "integer",
                    "sentiment": "positive|negative|neutral",
                    "confidence": "number 0-100",
                    "reasoning": "string",
                }
            ]
        },
    }


def validate_classifications(
    prepared: dict[str, Any],
    classifications: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    candidates = {
        article["article_index"]: article
        for article in prepared.get("articles", [])
    }
    validated = []
    seen = set()

    for item in classifications or []:
        if not isinstance(item, dict):
            continue
        article_index = item.get("article_index")
        sentiment = str(item.get("sentiment") or "").lower()
        if (
            not isinstance(article_index, int)
            or isinstance(article_index, bool)
            or article_index not in candidates
            or article_index in seen
            or sentiment not in VALID_SENTIMENTS
        ):
            continue
        try:
            confidence = float(item.get("confidence"))
        except (TypeError, ValueError):
            continue
        if not 0 <= confidence <= 100:
            continue

        candidate = candidates[article_index]
        validated.append(
            {
                "article_index": article_index,
                "headline": candidate["headline"],
                "sentiment": sentiment,
                "confidence": confidence,
                "reasoning": str(item.get("reasoning") or "").strip(),
            }
        )
        seen.add(article_index)

    return validated


def analyze_news_sentiment(
    news_data: dict[str, Any],
    ticker: str,
    llm_classifications: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """
    기존 sentiment와 현재 스킬 LLM의 분류를 합쳐 최종 신호를 계산한다.

    llm_classifications는 prepare_news_for_llm()의 response_schema를 따라야 한다.
    이 함수 자체는 네트워크나 외부 LLM API를 호출하지 않는다.
    """
    company_news = news_data.get("company_news", [])
    if not company_news:
        return {
            "signal": "neutral",
            "confidence": 0,
            "reasoning": "분석할 뉴스 기사가 없습니다.",
            "metrics": {
                "total_articles": 0,
                "bullish_articles": 0,
                "bearish_articles": 0,
                "neutral_articles": 0,
                "articles_classified_by_llm": 0,
                "articles_pending_llm": 0,
            },
        }

    prepared = prepare_news_for_llm(news_data, ticker)
    llm_analyzed = validate_classifications(prepared, llm_classifications)

    existing_sentiments = {sentiment: 0 for sentiment in VALID_SENTIMENTS}
    for news in company_news:
        sentiment = str(news.get("sentiment") or "").lower()
        if sentiment in existing_sentiments:
            existing_sentiments[sentiment] += 1

    llm_sentiments = {sentiment: 0 for sentiment in VALID_SENTIMENTS}
    for analyzed in llm_analyzed:
        llm_sentiments[analyzed["sentiment"]] += 1

    bullish_count = existing_sentiments["positive"] + llm_sentiments["positive"]
    bearish_count = existing_sentiments["negative"] + llm_sentiments["negative"]
    neutral_count = existing_sentiments["neutral"] + llm_sentiments["neutral"]
    total_count = len(company_news)

    if bullish_count > bearish_count:
        signal = "bullish"
    elif bearish_count > bullish_count:
        signal = "bearish"
    else:
        signal = "neutral"

    if llm_analyzed:
        matching_confidences = [
            analyzed["confidence"]
            for analyzed in llm_analyzed
            if (
                (signal == "bullish" and analyzed["sentiment"] == "positive")
                or (signal == "bearish" and analyzed["sentiment"] == "negative")
                or (signal == "neutral" and analyzed["sentiment"] == "neutral")
            )
        ]
        avg_llm_confidence = (
            sum(matching_confidences) / len(matching_confidences)
            if matching_confidences
            else 50
        )
        signal_proportion = (
            max(bullish_count, bearish_count, neutral_count) / total_count * 100
            if total_count
            else 0
        )
        confidence = int(0.7 * avg_llm_confidence + 0.3 * signal_proportion)
    else:
        confidence = (
            int(max(bullish_count, bearish_count, neutral_count) / total_count * 100)
            if total_count
            else 0
        )

    pending_count = max(0, len(prepared["articles"]) - len(llm_analyzed))
    reasoning_parts = [
        f"{ticker} 뉴스 {total_count}건을 집계했습니다.",
        (
            f"분포는 bullish {bullish_count}건, bearish {bearish_count}건, "
            f"neutral {neutral_count}건입니다."
        ),
    ]
    if llm_analyzed:
        reasoning_parts.append(
            f"현재 스킬 LLM이 기존 sentiment가 없던 기사 {len(llm_analyzed)}건을 분류했습니다."
        )
    if pending_count:
        reasoning_parts.append(f"LLM 분류가 필요한 기사 {pending_count}건이 남았습니다.")
    reasoning_parts.append(f"종합 심리는 {signal}, 신뢰도는 {confidence}%입니다.")

    return {
        "signal": signal,
        "confidence": confidence,
        "reasoning": " ".join(reasoning_parts),
        "metrics": {
            "total_articles": total_count,
            "bullish_articles": bullish_count,
            "bearish_articles": bearish_count,
            "neutral_articles": neutral_count,
            "articles_classified_by_llm": len(llm_analyzed),
            "articles_pending_llm": pending_count,
        },
    }


def _read_json(path: str | None) -> Any:
    if path:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    return json.load(sys.stdin)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Prepare or aggregate news sentiment without an external LLM API"
    )
    parser.add_argument("--ticker", required=True, help="Stock ticker (e.g., NVDA)")
    parser.add_argument("--input", help="Input JSON file; otherwise read stdin")
    parser.add_argument(
        "--classifications",
        help="Current skill LLM classifications JSON file",
    )
    parser.add_argument(
        "--prepare",
        action="store_true",
        help="Output the classification task for the current skill LLM",
    )
    args = parser.parse_args()

    input_data = _read_json(args.input)
    if args.prepare:
        result = prepare_news_for_llm(input_data, args.ticker)
    else:
        classifications = input_data.get("llm_classifications")
        if args.classifications:
            classification_payload = _read_json(args.classifications)
            classifications = (
                classification_payload.get("classifications", [])
                if isinstance(classification_payload, dict)
                else classification_payload
            )
        result = analyze_news_sentiment(input_data, args.ticker, classifications)

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
