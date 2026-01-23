#!/usr/bin/env python3
"""
Ensemble Analyzer

다중 투자자/분석가 신호를 종합하여 앙상블 분석 결과를 생성합니다.
"""
import json
import argparse
from typing import Dict, List, Any


# 투자자별 가중치 (역사적 성과 기반)
INVESTOR_WEIGHTS = {
    "warren-buffett-analyst": 1.0,       # 장기 복리 성과 최고
    "charlie-munger-analyst": 0.95,      # 버핏 파트너
    "aswath-damodaran-analyst": 0.90,    # DCF 전문가
    "peter-lynch-analyst": 0.85,         # GARP 선구자
    "ben-graham-analyst": 0.85,          # 가치 투자의 아버지
    "phil-fisher-analyst": 0.82,         # 성장주 선구자
    "stanley-druckenmiller-analyst": 0.80,  # 매크로 전문
    "mohnish-pabrai-analyst": 0.78,      # Dhandho 투자자
    "michael-burry-analyst": 0.75,       # 반대매매 전문
    "bill-ackman-analyst": 0.75,         # 행동주의 투자자
    "rakesh-jhunjhunwala-analyst": 0.72, # 신흥시장 전문
    "cathie-wood-analyst": 0.70,         # 고위험 고수익 혁신
    # 분석가 에이전트
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
        signal_val = SIGNAL_VALUES.get(data.get("signal", "neutral"), 0.0)
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
    agreement_ratio = max(len(bullish_investors), len(bearish_investors)) / len(signals) if signals else 0
    confidence = min(100, int(abs(ensemble_score) * 60 + agreement_ratio * 40))

    return {
        "signal": overall_signal,
        "ensemble_score": round(ensemble_score, 3),
        "confidence": confidence,
        "bullish_investors": bullish_investors,
        "bearish_investors": bearish_investors,
        "neutral_investors": neutral_investors,
        "total_analysts": len(signals),
        "agreement_ratio": round(agreement_ratio, 2),
    }


def predict_return(ensemble_score: float, volatility: float = 0.3, momentum_factor: float = 0.0) -> float:
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


def rank_tickers(ticker_signals: Dict[str, Dict[str, Any]], period: str = "3M") -> List[Dict[str, Any]]:
    """
    다중 종목의 앙상블 결과를 기반으로 순위 산정.

    Args:
        ticker_signals: {ticker: {agent: {signal, confidence, reasoning}}}
        period: 예측 기간

    Returns:
        순위가 매겨진 종목 리스트
    """
    results = []

    for ticker, signals in ticker_signals.items():
        ensemble = calculate_ensemble_score(signals)
        predicted_return = predict_return(ensemble["ensemble_score"])

        results.append({
            "ticker": ticker,
            "ensemble_score": ensemble["ensemble_score"],
            "signal": ensemble["signal"],
            "confidence": ensemble["confidence"],
            "predicted_return": f"{predicted_return * 100:.1f}%",
            "top_bullish": ensemble["bullish_investors"][:3],
            "top_bearish": ensemble["bearish_investors"][:3],
        })

    # 앙상블 점수로 정렬
    results.sort(key=lambda x: x["ensemble_score"], reverse=True)

    # 순위 부여
    for i, result in enumerate(results):
        result["rank"] = i + 1

    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ensemble analysis of investor signals")
    parser.add_argument("--signals", type=str, required=True, help="JSON file with signals")
    parser.add_argument("--output", type=str, default=None, help="Output file (optional)")

    args = parser.parse_args()

    with open(args.signals, "r") as f:
        signals = json.load(f)

    # 단일 종목인지 다중 종목인지 확인
    first_key = list(signals.keys())[0]
    if isinstance(signals[first_key], dict) and "signal" in signals[first_key]:
        # 단일 종목
        result = calculate_ensemble_score(signals)
    else:
        # 다중 종목
        result = rank_tickers(signals)

    output = json.dumps(result, indent=2)

    if args.output:
        with open(args.output, "w") as f:
            f.write(output)
        print(f"Results saved to {args.output}")
    else:
        print(output)
