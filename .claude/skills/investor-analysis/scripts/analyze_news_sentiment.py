#!/usr/bin/env python3
"""
뉴스 심리 분석 스크립트
LLM을 사용하여 뉴스 헤드라인의 sentiment를 분석합니다.
"""
import json
import os
import sys
from typing import Dict, Any

def analyze_news_sentiment(news_data: dict, ticker: str) -> dict:
    """
    뉴스 데이터를 분석하여 bullish/bearish/neutral 신호 생성
    
    Args:
        news_data: get_company_news()에서 반환된 뉴스 데이터
        ticker: 종목 코드
    
    Returns:
        {
            "signal": "bullish|bearish|neutral",
            "confidence": 0-100,
            "reasoning": "분석 근거",
            "metrics": {
                "total_articles": N,
                "bullish_articles": N,
                "bearish_articles": N,
                "neutral_articles": N,
                "articles_classified_by_llm": N
            }
        }
    """
    company_news = news_data.get("company_news", [])
    
    if not company_news:
        return {
            "signal": "neutral",
            "confidence": 0,
            "reasoning": "No news articles available for analysis",
            "metrics": {
                "total_articles": 0,
                "bullish_articles": 0,
                "bearish_articles": 0,
                "neutral_articles": 0,
                "articles_classified_by_llm": 0
            }
        }
    
    # 최신 10개 기사 중 sentiment 없는 것 추출
    recent_news = company_news[:10]
    news_without_sentiment = [
        news for news in recent_news 
        if news.get("sentiment") is None
    ]
    
    # LLM 분석할 기사 선택 (최대 5개)
    news_to_analyze = news_without_sentiment[:5]
    
    # LLM으로 sentiment 분석
    llm_analyzed = []
    
    try:
        from openai import OpenAI
        
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            print("Warning: OPENAI_API_KEY not set", file=sys.stderr)
        else:
            client = OpenAI(api_key=api_key)
            
            for news in news_to_analyze:
                headline = news.get("summary", "") or news.get("title", "")
                if not headline:
                    continue
                
                try:
                    response = client.chat.completions.create(
                        model="gpt-4o-mini",
                        messages=[
                            {
                                "role": "user",
                                "content": f"""Please analyze the sentiment of the following news headline
with the following context:
The stock is {ticker}.
Determine if sentiment is 'positive', 'negative', or 'neutral'
for the stock {ticker} only.
Also provide a confidence score for your prediction from 0 to 100.
Respond in JSON format.

Headline: {headline}

Response format:
{{
  "sentiment": "positive|negative|neutral",
  "confidence": 0-100
}}"""
                            }
                        ],
                        temperature=0.3,
                        max_tokens=150
                    )
                    
                    result_text = response.choices[0].message.content.strip()
                    # JSON 파싱
                    if result_text.startswith("```json"):
                        result_text = result_text[7:]
                    if result_text.endswith("```"):
                        result_text = result_text[:-3]
                    result_text = result_text.strip()
                    
                    result = json.loads(result_text)
                    llm_analyzed.append({
                        "headline": headline[:100] + "..." if len(headline) > 100 else headline,
                        "sentiment": result["sentiment"],
                        "confidence": result["confidence"]
                    })
                    
                    print(f"Analyzed: {headline[:60]}... -> {result['sentiment']} (confidence: {result['confidence']})", file=sys.stderr)
                except Exception as e:
                    print(f"LLM 분석 실패: {e}", file=sys.stderr)
                    continue
    except ImportError:
        print("Warning: openai library not installed", file=sys.stderr)
    
    # 기존 sentiment가 있는 기사 집계
    existing_sentiments = {
        "positive": 0,
        "negative": 0,
        "neutral": 0
    }
    
    for news in company_news:
        sentiment = news.get("sentiment")
        if sentiment in existing_sentiments:
            existing_sentiments[sentiment] += 1
    
    # LLM 분석 결과 집계
    llm_sentiments = {
        "positive": 0,
        "negative": 0,
        "neutral": 0
    }
    
    for analyzed in llm_analyzed:
        sentiment = analyzed["sentiment"]
        if sentiment in llm_sentiments:
            llm_sentiments[sentiment] += 1
    
    # 전체 집계
    bullish_count = existing_sentiments["positive"] + llm_sentiments["positive"]
    bearish_count = existing_sentiments["negative"] + llm_sentiments["negative"]
    neutral_count = existing_sentiments["neutral"] + llm_sentiments["neutral"]
    total_count = len(company_news)
    
    # 신호 결정
    if bullish_count > bearish_count:
        signal = "bullish"
    elif bearish_count > bullish_count:
        signal = "bearish"
    else:
        signal = "neutral"
    
    # 신뢰도 계산
    if llm_analyzed:
        # LLM 분석 결과의 평균 confidence
        matching_confidences = [
            a["confidence"] for a in llm_analyzed
            if (signal == "bullish" and a["sentiment"] == "positive") or
               (signal == "bearish" and a["sentiment"] == "negative") or
               (signal == "neutral" and a["sentiment"] == "neutral")
        ]
        
        if matching_confidences:
            avg_llm_confidence = sum(matching_confidences) / len(matching_confidences)
        else:
            avg_llm_confidence = 50
        
        signal_proportion = max(bullish_count, bearish_count, neutral_count) / total_count * 100 if total_count > 0 else 0
        confidence = int(0.7 * avg_llm_confidence + 0.3 * signal_proportion)
    else:
        # LLM 분석 없이 기존 sentiment만 사용
        confidence = int(max(bullish_count, bearish_count, neutral_count) / total_count * 100) if total_count > 0 else 0
    
    # Reasoning 생성
    reasoning_parts = [
        f"Analyzed {total_count} news articles for {ticker}.",
        f"Distribution: {bullish_count} bullish, {bearish_count} bearish, {neutral_count} neutral.",
    ]
    
    if llm_analyzed:
        reasoning_parts.append(f"LLM analyzed {len(llm_analyzed)} recent articles without existing sentiment.")
        # 샘플 헤드라인 추가
        sample_headlines = [a["headline"] for a in llm_analyzed[:3]]
        if sample_headlines:
            reasoning_parts.append(f"Sample headlines analyzed: {'; '.join(sample_headlines)}")
    
    reasoning_parts.append(f"Overall sentiment is {signal} with confidence {confidence}%.")
    
    reasoning = " ".join(reasoning_parts)
    
    return {
        "signal": signal,
        "confidence": confidence,
        "reasoning": reasoning,
        "metrics": {
            "total_articles": total_count,
            "bullish_articles": bullish_count,
            "bearish_articles": bearish_count,
            "neutral_articles": neutral_count,
            "articles_classified_by_llm": len(llm_analyzed)
        }
    }


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Analyze news sentiment using LLM")
    parser.add_argument("--ticker", type=str, required=True, help="Stock ticker (e.g., NVDA)")
    parser.add_argument("--input", type=str, help="Input JSON file (if not provided, reads from stdin)")
    
    args = parser.parse_args()
    
    if args.input:
        with open(args.input, 'r') as f:
            input_data = json.load(f)
    else:
        input_data = json.load(sys.stdin)
    
    result = analyze_news_sentiment(input_data, args.ticker)
    print(json.dumps(result, indent=2))
