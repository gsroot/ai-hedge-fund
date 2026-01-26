#!/usr/bin/env python3
"""
Ranking Algorithm for Profit Prediction

다중 투자자 신호를 종합하여 종목 순위를 산정하고 수익률을 예측합니다.
최대 300개 이상의 종목을 배치 처리할 수 있도록 설계되었습니다.
"""
import json
import argparse
import os
import hashlib
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

# 캐시 디렉토리
CACHE_DIR = Path.home() / ".cache" / "profit-predictor"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# 기본 설정
DEFAULT_BATCH_SIZE = 50  # 배치당 종목 수
MAX_WORKERS = 10  # 병렬 처리 워커 수
MAX_TICKERS = 500  # 최대 처리 가능 종목 수


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


# ============================================================================
# 대량 종목 처리를 위한 확장 기능 (최대 300+ 종목)
# ============================================================================

def get_cache_key(ticker: str, date: str) -> str:
    """캐시 키 생성"""
    return hashlib.md5(f"{ticker}:{date}".encode()).hexdigest()


def load_cached_signal(ticker: str, date: str) -> Optional[Dict[str, Any]]:
    """캐시된 신호 로드"""
    cache_file = CACHE_DIR / f"{get_cache_key(ticker, date)}.json"
    if cache_file.exists():
        try:
            with open(cache_file, "r") as f:
                cached = json.load(f)
                # 캐시 유효기간: 24시간
                cached_time = datetime.fromisoformat(cached.get("cached_at", "2000-01-01"))
                if (datetime.now() - cached_time).total_seconds() < 86400:
                    return cached.get("signals")
        except (json.JSONDecodeError, ValueError):
            pass
    return None


def save_cached_signal(ticker: str, date: str, signals: Dict[str, Any]) -> None:
    """신호 캐시 저장"""
    cache_file = CACHE_DIR / f"{get_cache_key(ticker, date)}.json"
    with open(cache_file, "w") as f:
        json.dump({
            "ticker": ticker,
            "date": date,
            "signals": signals,
            "cached_at": datetime.now().isoformat()
        }, f)


def clear_cache(max_age_days: int = 7) -> int:
    """오래된 캐시 정리"""
    cleared = 0
    cutoff = datetime.now().timestamp() - (max_age_days * 86400)
    for cache_file in CACHE_DIR.glob("*.json"):
        if cache_file.stat().st_mtime < cutoff:
            cache_file.unlink()
            cleared += 1
    return cleared


def process_ticker_batch(
    tickers: List[str],
    signals_data: Dict[str, Dict[str, Dict[str, Any]]],
    volatilities: Optional[Dict[str, float]] = None,
    momentum_factors: Optional[Dict[str, float]] = None,
) -> List[Dict[str, Any]]:
    """
    종목 배치 처리 (내부 함수).

    Args:
        tickers: 처리할 종목 리스트
        signals_data: 전체 신호 데이터
        volatilities: 종목별 변동성
        momentum_factors: 종목별 모멘텀

    Returns:
        배치 결과 리스트
    """
    results = []
    volatilities = volatilities or {}
    momentum_factors = momentum_factors or {}

    for ticker in tickers:
        if ticker not in signals_data:
            continue

        signals = signals_data[ticker]
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

    return results


def rank_tickers_batch(
    ticker_signals: Dict[str, Dict[str, Dict[str, Any]]],
    period: str = "3M",
    volatilities: Optional[Dict[str, float]] = None,
    momentum_factors: Optional[Dict[str, float]] = None,
    batch_size: int = DEFAULT_BATCH_SIZE,
    max_workers: int = MAX_WORKERS,
    progress_callback: Optional[callable] = None,
) -> Dict[str, Any]:
    """
    대량 종목 배치 처리 및 순위 산정 (최대 300+ 종목 지원).

    Args:
        ticker_signals: {ticker: {agent: {signal, confidence, reasoning}}}
        period: 예측 기간
        volatilities: {ticker: volatility} 종목별 변동성
        momentum_factors: {ticker: momentum} 종목별 모멘텀
        batch_size: 배치당 종목 수 (기본: 50)
        max_workers: 병렬 워커 수 (기본: 10)
        progress_callback: 진행률 콜백 함수 (processed_count, total_count)

    Returns:
        순위가 매겨진 종목 리스트와 메타데이터
    """
    tickers = list(ticker_signals.keys())
    total_count = len(tickers)

    if total_count > MAX_TICKERS:
        print(f"경고: 종목 수({total_count})가 최대 허용치({MAX_TICKERS})를 초과합니다. 상위 {MAX_TICKERS}개만 처리합니다.")
        tickers = tickers[:MAX_TICKERS]
        total_count = MAX_TICKERS

    # 배치로 분할
    batches = [tickers[i:i + batch_size] for i in range(0, len(tickers), batch_size)]
    all_results = []
    processed_count = 0
    lock = threading.Lock()

    def process_and_track(batch: List[str]) -> List[Dict[str, Any]]:
        nonlocal processed_count
        results = process_ticker_batch(batch, ticker_signals, volatilities, momentum_factors)
        with lock:
            processed_count += len(batch)
            if progress_callback:
                progress_callback(processed_count, total_count)
        return results

    # 병렬 처리
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(process_and_track, batch) for batch in batches]

        for future in as_completed(futures):
            try:
                batch_results = future.result()
                all_results.extend(batch_results)
            except Exception as e:
                print(f"배치 처리 중 오류: {e}")

    # 앙상블 점수로 정렬 (내림차순)
    all_results.sort(key=lambda x: x["ensemble_score"], reverse=True)

    # 순위 부여
    for i, result in enumerate(all_results):
        result["rank"] = i + 1

    return {
        "rankings": all_results,
        "methodology": "17개 투자자 앙상블 + 모멘텀/변동성 조정 (배치 처리)",
        "period": period,
        "total_tickers": len(all_results),
        "batch_size": batch_size,
        "batches_processed": len(batches),
    }


def get_top_picks(
    rankings: Dict[str, Any],
    top_n: int = 10,
    min_confidence: int = 60,
    signal_filter: Optional[str] = "bullish"
) -> List[Dict[str, Any]]:
    """
    순위 결과에서 상위 종목 필터링.

    Args:
        rankings: rank_tickers 또는 rank_tickers_batch 결과
        top_n: 상위 N개 (기본: 10)
        min_confidence: 최소 신뢰도 (기본: 60)
        signal_filter: 신호 필터 ("bullish", "bearish", None)

    Returns:
        필터링된 상위 종목 리스트
    """
    results = rankings.get("rankings", [])

    filtered = [
        r for r in results
        if r["confidence"] >= min_confidence
        and (signal_filter is None or r["signal"] == signal_filter)
    ]

    return filtered[:top_n]


def generate_report(
    rankings: Dict[str, Any],
    output_format: str = "text"
) -> str:
    """
    순위 결과를 리포트 형식으로 생성.

    Args:
        rankings: rank_tickers 결과
        output_format: "text", "markdown", "json"

    Returns:
        포맷된 리포트 문자열
    """
    results = rankings.get("rankings", [])
    total = rankings.get("total_tickers", 0)
    period = rankings.get("period", "3M")

    if output_format == "json":
        return json.dumps(rankings, indent=2, ensure_ascii=False)

    if output_format == "markdown":
        lines = [
            f"# 수익률 예측 리포트",
            f"",
            f"- **분석 종목 수**: {total}개",
            f"- **예측 기간**: {period}",
            f"- **분석 방법론**: {rankings.get('methodology', 'N/A')}",
            f"",
            f"## 상위 20개 종목",
            f"",
            f"| 순위 | 종목 | 신호 | 점수 | 예상수익률 | 신뢰도 |",
            f"|------|------|------|------|------------|--------|",
        ]
        for r in results[:20]:
            lines.append(
                f"| {r['rank']} | {r['ticker']} | {r['signal']} | "
                f"{r['ensemble_score']:.3f} | {r['predicted_return']} | {r['confidence']}% |"
            )

        if total > 20:
            lines.append(f"")
            lines.append(f"*... 외 {total - 20}개 종목*")

        return "\n".join(lines)

    # text format
    lines = [
        f"=" * 60,
        f"수익률 예측 리포트",
        f"=" * 60,
        f"분석 종목 수: {total}개",
        f"예측 기간: {period}",
        f"",
        f"상위 20개 종목:",
        f"-" * 60,
    ]
    for r in results[:20]:
        lines.append(
            f"{r['rank']:3d}. {r['ticker']:6s} | {r['signal']:8s} | "
            f"점수: {r['ensemble_score']:+.3f} | 예상: {r['predicted_return']:>7s} | "
            f"신뢰도: {r['confidence']:3d}%"
        )

    if total > 20:
        lines.append(f"")
        lines.append(f"... 외 {total - 20}개 종목")

    return "\n".join(lines)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Rank tickers based on ensemble analysis (supports 300+ tickers)"
    )
    parser.add_argument("--signals", type=str, required=True,
                       help="JSON file with signals: {ticker: {agent: {signal, confidence, reasoning}}}")
    parser.add_argument("--period", type=str, default="3M", help="Prediction period")
    parser.add_argument("--output", type=str, default=None, help="Output file (optional)")
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE,
                       help=f"Batch size for processing (default: {DEFAULT_BATCH_SIZE})")
    parser.add_argument("--workers", type=int, default=MAX_WORKERS,
                       help=f"Number of parallel workers (default: {MAX_WORKERS})")
    parser.add_argument("--format", type=str, choices=["json", "text", "markdown"],
                       default="json", help="Output format (default: json)")
    parser.add_argument("--top", type=int, default=None,
                       help="Show only top N results")
    parser.add_argument("--clear-cache", action="store_true",
                       help="Clear old cache files before processing")

    args = parser.parse_args()

    # 캐시 정리
    if args.clear_cache:
        cleared = clear_cache()
        print(f"캐시 정리 완료: {cleared}개 파일 삭제")

    with open(args.signals, "r") as f:
        ticker_signals = json.load(f)

    total_tickers = len(ticker_signals)
    print(f"분석 시작: {total_tickers}개 종목")

    # 진행률 표시 콜백
    def progress_callback(processed: int, total: int):
        pct = (processed / total) * 100
        print(f"\r진행: {processed}/{total} ({pct:.1f}%)", end="", flush=True)

    # 대량 종목(50개 초과)은 배치 처리
    if total_tickers > 50:
        result = rank_tickers_batch(
            ticker_signals,
            period=args.period,
            batch_size=args.batch_size,
            max_workers=args.workers,
            progress_callback=progress_callback
        )
        print()  # 진행률 줄바꿈
    else:
        result = rank_tickers(ticker_signals, args.period)

    # 상위 N개만 출력
    if args.top:
        result["rankings"] = result["rankings"][:args.top]
        result["showing_top"] = args.top

    # 출력 포맷
    if args.format == "json":
        output = json.dumps(result, indent=2, ensure_ascii=False)
    else:
        output = generate_report(result, args.format)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(output)
        print(f"결과 저장: {args.output}")
    else:
        print(output)

    # 요약 출력
    if args.format != "json":
        bullish_count = sum(1 for r in result["rankings"] if r["signal"] == "bullish")
        bearish_count = sum(1 for r in result["rankings"] if r["signal"] == "bearish")
        print(f"\n요약: Bullish {bullish_count}개, Bearish {bearish_count}개, "
              f"Neutral {len(result['rankings']) - bullish_count - bearish_count}개")
