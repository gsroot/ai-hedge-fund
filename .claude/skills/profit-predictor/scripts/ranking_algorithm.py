#!/usr/bin/env python3
"""
Ranking Algorithm for Profit Prediction

다중 투자자 신호를 종합하여 종목 순위를 산정하고 수익률을 예측합니다.
"""
import json
import argparse
from typing import Dict, List, Any, Optional


# 투자자별 가중치 (역사적 성과 기반)
INVESTOR_WEIGHTS = {
    # 가치 투자자
    "warren-buffett-analyst": 1.00,
    "charlie-munger-analyst": 0.95,
    "ben-graham-analyst": 0.85,
    "mohnish-pabrai-analyst": 0.78,

    # 성장 투자자
    "peter-lynch-analyst": 0.85,
    "phil-fisher-analyst": 0.82,
    "cathie-wood-analyst": 0.70,
    "rakesh-jhunjhunwala-analyst": 0.72,

    # 특수 전략
    "michael-burry-analyst": 0.75,
    "bill-ackman-analyst": 0.75,
    "stanley-druckenmiller-analyst": 0.80,
    "aswath-damodaran-analyst": 0.90,

    # 분석가
    "technical-analyst": 0.65,
    "fundamentals-analyst": 0.70,
    "growth-analyst": 0.68,
    "sentiment-analyst": 0.60,
    "news-sentiment-analyst": 0.55,
}

# 신호 수치화
SIGNAL_VALUES = {
    "bullish": 1.0,
    "neutral": 0.0,
    "bearish": -1.0,
}


def calculate_ensemble_score(signals: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """
    다중 투자자 신호를 종합하여 앙상블 점수 계산.

    Args:
        signals: {agent_name: {signal, confidence, reasoning}}

    Returns:
        앙상블 분석 결과
    """
    weighted_sum = 0.0
    total_weight = 0.0
    bullish_investors = []
    bearish_investors = []
    neutral_investors = []

    for investor, data in signals.items():
        weight = INVESTOR_WEIGHTS.get(investor, 0.5)
        signal = data.get("signal", "neutral")
        signal_val = SIGNAL_VALUES.get(signal, 0.0)
        confidence = data.get("confidence", 50) / 100.0

        # 가중 합산: 신호 × 신뢰도 × 투자자 가중치
        weighted_sum += signal_val * confidence * weight
        total_weight += weight * confidence

        # 투자자 분류
        if signal_val > 0:
            bullish_investors.append(investor)
        elif signal_val < 0:
            bearish_investors.append(investor)
        else:
            neutral_investors.append(investor)

    # 앙상블 점수: -1.0 ~ 1.0
    ensemble_score = weighted_sum / total_weight if total_weight > 0 else 0.0

    # 최종 신호 결정
    if ensemble_score > 0.3:
        overall_signal = "bullish"
    elif ensemble_score < -0.3:
        overall_signal = "bearish"
    else:
        overall_signal = "neutral"

    # 신뢰도 계산 (합의 정도 기반)
    total_analysts = len(signals)
    agreement_ratio = max(len(bullish_investors), len(bearish_investors)) / total_analysts if total_analysts > 0 else 0
    confidence = min(100, int(abs(ensemble_score) * 60 + agreement_ratio * 40))

    return {
        "signal": overall_signal,
        "ensemble_score": round(ensemble_score, 3),
        "confidence": confidence,
        "bullish_investors": bullish_investors,
        "bearish_investors": bearish_investors,
        "neutral_investors": neutral_investors,
        "total_analysts": total_analysts,
        "agreement_ratio": round(agreement_ratio, 2),
    }


def predict_return(
    ensemble_score: float,
    volatility: float = 0.3,
    momentum_factor: float = 0.0
) -> float:
    """
    앙상블 점수와 시장 요인을 기반으로 예상 수익률 추정.

    Args:
        ensemble_score: 앙상블 점수 (-1.0 ~ 1.0)
        volatility: 변동성 (연율화, 0.0 ~ 1.0)
        momentum_factor: 모멘텀 요인 (-1.0 ~ 1.0)

    Returns:
        예상 수익률 (소수점, 예: 0.15 = 15%)
    """
    # 기본 수익률: 앙상블 점수 기반 (최대 ±20%)
    base_return = ensemble_score * 0.20

    # 리스크 조정: 변동성이 높으면 수익률 감소
    risk_adjusted = base_return * (1 - volatility * 0.5)

    # 모멘텀 조정: 모멘텀이 방향과 같으면 수익률 증가
    momentum_adjusted = risk_adjusted * (1 + momentum_factor * 0.3)

    return round(momentum_adjusted, 4)


def extract_key_factors(signals: Dict[str, Dict[str, Any]], overall_signal: str) -> List[str]:
    """
    신호와 일치하는 투자자들의 주요 reasoning에서 핵심 요인 추출.
    """
    factors = []

    for investor, data in signals.items():
        signal = data.get("signal", "neutral")
        reasoning = data.get("reasoning", "")

        # 전체 신호와 같은 방향의 투자자만
        if (overall_signal == "bullish" and signal == "bullish") or \
           (overall_signal == "bearish" and signal == "bearish"):
            # reasoning에서 주요 키워드 추출 (간단한 휴리스틱)
            if "ROE" in reasoning or "수익률" in reasoning:
                factors.append("강한 수익성")
            if "안전마진" in reasoning or "margin" in reasoning.lower():
                factors.append("안전마진 확보")
            if "FCF" in reasoning or "현금흐름" in reasoning:
                factors.append("양호한 현금흐름")
            if "moat" in reasoning.lower() or "경쟁우위" in reasoning:
                factors.append("경쟁우위 보유")
            if "성장" in reasoning or "growth" in reasoning.lower():
                factors.append("성장 잠재력")
            if "저평가" in reasoning or "undervalued" in reasoning.lower():
                factors.append("저평가 상태")

    # 중복 제거 및 상위 5개만
    return list(dict.fromkeys(factors))[:5]


def rank_tickers(
    ticker_signals: Dict[str, Dict[str, Dict[str, Any]]],
    period: str = "3M",
    volatilities: Optional[Dict[str, float]] = None,
    momentum_factors: Optional[Dict[str, float]] = None
) -> Dict[str, Any]:
    """
    다중 종목의 앙상블 결과를 기반으로 순위 산정.

    Args:
        ticker_signals: {ticker: {agent: {signal, confidence, reasoning}}}
        period: 예측 기간
        volatilities: {ticker: volatility} 종목별 변동성
        momentum_factors: {ticker: momentum} 종목별 모멘텀

    Returns:
        순위가 매겨진 종목 리스트와 메타데이터
    """
    results = []
    volatilities = volatilities or {}
    momentum_factors = momentum_factors or {}

    for ticker, signals in ticker_signals.items():
        ensemble = calculate_ensemble_score(signals)

        volatility = volatilities.get(ticker, 0.3)
        momentum = momentum_factors.get(ticker, 0.0)
        predicted_return = predict_return(
            ensemble["ensemble_score"],
            volatility,
            momentum
        )

        key_factors = extract_key_factors(signals, ensemble["signal"])

        results.append({
            "ticker": ticker,
            "ensemble_score": ensemble["ensemble_score"],
            "signal": ensemble["signal"],
            "confidence": ensemble["confidence"],
            "predicted_return": f"{predicted_return * 100:.1f}%",
            "predicted_return_value": predicted_return,
            "top_bullish": ensemble["bullish_investors"][:3],
            "top_bearish": ensemble["bearish_investors"][:3],
            "key_factors": key_factors if key_factors else ["데이터 분석 중"],
            "agreement_ratio": ensemble["agreement_ratio"],
        })

    # 앙상블 점수로 정렬 (내림차순)
    results.sort(key=lambda x: x["ensemble_score"], reverse=True)

    # 순위 부여
    for i, result in enumerate(results):
        result["rank"] = i + 1

    return {
        "rankings": results,
        "methodology": "17개 투자자 앙상블 + 모멘텀/변동성 조정",
        "period": period,
        "total_tickers": len(results),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Rank tickers based on ensemble analysis")
    parser.add_argument("--signals", type=str, required=True,
                       help="JSON file with signals: {ticker: {agent: {signal, confidence, reasoning}}}")
    parser.add_argument("--period", type=str, default="3M", help="Prediction period")
    parser.add_argument("--output", type=str, default=None, help="Output file (optional)")

    args = parser.parse_args()

    with open(args.signals, "r") as f:
        ticker_signals = json.load(f)

    result = rank_tickers(ticker_signals, args.period)

    output = json.dumps(result, indent=2, ensure_ascii=False)

    if args.output:
        with open(args.output, "w") as f:
            f.write(output)
        print(f"Results saved to {args.output}")
    else:
        print(output)
