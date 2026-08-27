#!/usr/bin/env python3
"""
뉴스 심리 분석 보조 스크립트.

별도 모델 API를 호출하지 않는다. 스킬을 실행 중인 현재 LLM이
prepare_news_for_llm()의 기사를 분류하고, 이 모듈은 그 결과를 검증·집계한다.
"""
import argparse
import html
import json
import re
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit


VALID_SENTIMENTS = {"positive", "negative", "neutral"}
VALID_RELEVANCE = {"relevant", "unrelated", "ambiguous"}
VALID_EVENT_TYPES = {
    "earnings_surprise",
    "guidance",
    "contract",
    "financing_dilution",
    "capital_return",
    "legal_regulatory",
    "product_partnership",
    "management",
    "market_price_recap",
    "routine_disclosure",
    "macro_industry",
    "other",
}
VALID_IMPACT_HORIZONS = {"intraday", "short", "medium", "long", "none"}
VALID_SURPRISES = {"positive", "negative", "none", "unknown"}
NON_ACTIONABLE_EVENT_TYPES = {"market_price_recap", "routine_disclosure"}
MIN_ACTIONABLE_CONFIDENCE = 60.0
MAX_RECENT_ARTICLES = 10
MAX_LLM_ARTICLES = 5


def _headline(news: dict[str, Any]) -> str:
    return str(news.get("summary") or news.get("title") or "").strip()


def _normalized_headline(value: str) -> str:
    plain = re.sub(r"<[^>]+>", " ", html.unescape(value)).lower()
    return re.sub(r"[^0-9a-z가-힣]+", "", plain)


def _canonical_link(value: Any) -> str:
    link = str(value or "").strip()
    if not link:
        return ""
    parsed = urlsplit(link)
    return urlunsplit(
        (
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            parsed.path.rstrip("/"),
            "",
            "",
        )
    )


def classification_exclusion_reason(classification: dict[str, Any]) -> str | None:
    """Return why a valid classification must not be used as decision evidence."""
    if classification.get("abstain"):
        return "llm_abstained"
    relevance = classification.get("relevance")
    if relevance == "unrelated":
        return "unrelated_entity"
    if relevance == "ambiguous":
        return "ambiguous_entity"
    if classification.get("event_type") in NON_ACTIONABLE_EVENT_TYPES:
        return "non_actionable_event"
    if float(classification.get("confidence", 0.0)) < MIN_ACTIONABLE_CONFIDENCE:
        return "low_confidence"
    return None


def prepare_news_for_llm(
    news_data: dict[str, Any],
    ticker: str,
    limit: int = MAX_LLM_ARTICLES,
) -> dict[str, Any]:
    """현재 스킬 LLM이 분류할 기사와 출력 계약을 만든다."""
    company_news = news_data.get("company_news", [])
    articles = []
    duplicate_articles = 0
    seen_headlines: set[str] = set()
    seen_links: set[str] = set()
    for article_index, news in enumerate(company_news[:MAX_RECENT_ARTICLES]):
        headline = _headline(news)
        if not headline:
            continue
        headline_key = _normalized_headline(headline)
        link_key = _canonical_link(news.get("link"))
        if (
            (headline_key and headline_key in seen_headlines)
            or (link_key and link_key in seen_links)
        ):
            duplicate_articles += 1
            continue
        if headline_key:
            seen_headlines.add(headline_key)
        if link_key:
            seen_links.add(link_key)
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
            "현재 스킬을 실행 중인 LLM이 각 기사의 종목 관련성을 먼저 판정하고, "
            "이벤트 유형·시장 기대 대비 surprise·영향 기간을 구분한 뒤 sentiment를 "
            "분류한다. 종목이 불명확하거나 근거가 부족하면 abstain=true로 반환한다. "
            "단순 주가 등락 요약은 market_price_recap, 반복·정형 공시는 "
            "routine_disclosure로 분류한다. 외부 모델 API를 호출하거나 모델을 지정하지 않는다."
        ),
        "duplicates_removed": duplicate_articles,
        "articles": articles,
        "response_schema": {
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
        relevance = str(item.get("relevance") or "").lower()
        event_type = str(item.get("event_type") or "").lower()
        surprise = str(item.get("surprise") or "").lower()
        impact_horizon = str(item.get("impact_horizon") or "").lower()
        abstain = item.get("abstain")
        if (
            not isinstance(article_index, int)
            or isinstance(article_index, bool)
            or article_index not in candidates
            or article_index in seen
            or sentiment not in VALID_SENTIMENTS
            or relevance not in VALID_RELEVANCE
            or event_type not in VALID_EVENT_TYPES
            or surprise not in VALID_SURPRISES
            or impact_horizon not in VALID_IMPACT_HORIZONS
            or not isinstance(abstain, bool)
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
                "date": candidate.get("date"),
                "publisher": candidate.get("publisher"),
                "link": candidate.get("link"),
                "content_type": candidate.get("content_type"),
                "relevance": relevance,
                "event_type": event_type,
                "sentiment": sentiment,
                "surprise": surprise,
                "impact_horizon": impact_horizon,
                "confidence": confidence,
                "abstain": abstain,
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
            "decision_use": "risk_and_explanation_only",
            "risk_flags": [],
            "metrics": {
                "total_articles": 0,
                "bullish_articles": 0,
                "bearish_articles": 0,
                "neutral_articles": 0,
                "articles_classified_by_llm": 0,
                "actionable_llm_articles": 0,
                "excluded_llm_articles": 0,
                "legacy_sentiment_labels_ignored": 0,
                "articles_pending_llm": 0,
            },
        }

    prepared = prepare_news_for_llm(news_data, ticker)
    llm_analyzed = validate_classifications(prepared, llm_classifications)
    actionable_llm = [
        item for item in llm_analyzed if classification_exclusion_reason(item) is None
    ]

    llm_sentiments = {sentiment: 0 for sentiment in VALID_SENTIMENTS}
    for analyzed in actionable_llm:
        llm_sentiments[analyzed["sentiment"]] += 1

    bullish_count = llm_sentiments["positive"]
    bearish_count = llm_sentiments["negative"]
    neutral_count = llm_sentiments["neutral"]
    total_count = len(company_news)

    if bullish_count > bearish_count:
        signal = "bullish"
    elif bearish_count > bullish_count:
        signal = "bearish"
    else:
        signal = "neutral"

    if actionable_llm:
        matching_confidences = [
            analyzed["confidence"]
            for analyzed in actionable_llm
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
    if actionable_llm:
        reasoning_parts.append(
            f"현재 스킬 LLM 분류 중 의사결정 근거로 사용할 수 있는 기사는 "
            f"{len(actionable_llm)}건입니다."
        )
    excluded_count = len(llm_analyzed) - len(actionable_llm)
    if excluded_count:
        reasoning_parts.append(
            f"무관·애매·정형 기사 또는 저신뢰 분류 {excluded_count}건은 제외했습니다."
        )
    if pending_count:
        reasoning_parts.append(f"LLM 분류가 필요한 기사 {pending_count}건이 남았습니다.")
    reasoning_parts.append(f"종합 심리는 {signal}, 신뢰도는 {confidence}%입니다.")

    risk_flags = [
        {
            "article_index": item["article_index"],
            "event_type": item["event_type"],
            "impact_horizon": item["impact_horizon"],
            "confidence": item["confidence"],
            "headline": item["headline"],
            "reasoning": item["reasoning"],
        }
        for item in actionable_llm
        if item["sentiment"] == "negative" and item["confidence"] >= 70
    ]

    return {
        "signal": signal,
        "confidence": confidence,
        "reasoning": " ".join(reasoning_parts),
        "decision_use": "risk_and_explanation_only",
        "risk_flags": risk_flags,
        "metrics": {
            "total_articles": total_count,
            "bullish_articles": bullish_count,
            "bearish_articles": bearish_count,
            "neutral_articles": neutral_count,
            "articles_classified_by_llm": len(llm_analyzed),
            "actionable_llm_articles": len(actionable_llm),
            "excluded_llm_articles": excluded_count,
            "legacy_sentiment_labels_ignored": sum(
                str(news.get("sentiment") or "").lower() in VALID_SENTIMENTS
                for news in company_news
            ),
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
