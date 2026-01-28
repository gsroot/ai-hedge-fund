"""
분석 파이프라인

단일 종목 종합 분석(analyze_single_ticker)과
배치 분석(run_batch_analysis)을 수행합니다.
"""
import statistics
import threading
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

from config import CACHE_ENABLED, FACTOR_WEIGHTS, INVESTOR_WEIGHTS, MAX_WORKERS
from cache import cache_stats
from data_fetcher import (
    get_financial_metrics,
    get_prices,
    get_insider_trades,
    get_company_news,
    batch_fetch_prices,
)
from factor_scoring import (
    get_market_cap_category,
    calculate_size_bonus,
    calculate_value_score,
    calculate_growth_score,
    calculate_quality_score,
    calculate_momentum_score,
    calculate_enhanced_momentum_score,
    calculate_safety_score,
    calculate_sentiment_score,
    calculate_insider_activity_score,
)
from investor_scoring import (
    calculate_sector_stats,
    calculate_buffett_score,
    calculate_lynch_score,
    calculate_graham_score,
    calculate_fisher_score,
    calculate_druckenmiller_score,
    generate_investor_warnings,
)
from ticker_utils import is_korean_ticker


def analyze_single_ticker(ticker, end_date, prefetched_prices=None, strategy="fundamental", skip_news=False, sector_stats=None):
    """
    단일 종목 종합 분석 (앙상블 투자자 점수 포함)

    Args:
        ticker: 종목 티커
        end_date: 분석 기준일
        prefetched_prices: 미리 배치로 가져온 가격 데이터 (선택사항)
        strategy: 분석 전략 (fundamental, momentum, hybrid)
        skip_news: True이면 뉴스/내부자 거래 조회 건너뜀
        sector_stats: 섹터별 통계 (상대적 밸류에이션용)
    """
    try:
        # 1. 재무 지표 수집
        metrics = get_financial_metrics(ticker, end_date, period="annual", limit=2)

        if not metrics:
            return None

        # 2. 가격 데이터
        if prefetched_prices is not None:
            prices = prefetched_prices
        else:
            end_dt = datetime.strptime(end_date, "%Y-%m-%d")
            start_dt = end_dt - timedelta(days=90)
            prices = get_prices(ticker, start_dt.strftime("%Y-%m-%d"), end_date)

        # 3. 내부자 거래 / 뉴스 데이터
        if skip_news:
            insider_trades = []
            company_news = []
        else:
            insider_trades = get_insider_trades(ticker, end_date, limit=50)
            company_news = get_company_news(ticker, end_date, limit=20)

        # 시가총액 (한국 종목은 KRW 단위)
        market_cap = metrics[0].get('market_cap')
        currency = "KRW" if is_korean_ticker(ticker) else None
        cap_category, cap_display = get_market_cap_category(market_cap, currency=currency)

        # ========================================
        # 기본 팩터별 점수 계산
        # ========================================
        value_score, value_factors = calculate_value_score(metrics)
        growth_score, growth_factors = calculate_growth_score(metrics)
        quality_score, quality_factors = calculate_quality_score(metrics)
        momentum_score, momentum_factors = calculate_momentum_score(prices)
        safety_score, safety_factors = calculate_safety_score(metrics)

        sentiment_score, sentiment_factors = calculate_sentiment_score(company_news)
        insider_score, insider_factors = calculate_insider_activity_score(insider_trades)

        size_bonus, size_factors = calculate_size_bonus(market_cap, growth_score, currency=currency)

        enhanced_momentum_score, momentum_details = calculate_enhanced_momentum_score(prices)

        # ========================================
        # 투자자 스타일별 점수 계산
        # ========================================
        investor_scores = {
            "buffett": calculate_buffett_score(metrics, growth_score, quality_score, safety_score),
            "lynch": calculate_lynch_score(metrics, growth_score, sentiment_score, insider_score, sector_stats),
            "graham": calculate_graham_score(metrics, sector_stats),
            "druckenmiller": calculate_druckenmiller_score(enhanced_momentum_score, growth_score, momentum_details, metrics),
            "fisher": calculate_fisher_score(metrics, growth_score, quality_score),
        }

        # ========================================
        # 앙상블 가중 점수 계산
        # ========================================
        ensemble_weighted_sum = 0
        ensemble_total_weight = 0

        for investor, inv_score in investor_scores.items():
            weight = INVESTOR_WEIGHTS.get(investor, 0.5)
            ensemble_weighted_sum += inv_score * weight
            ensemble_total_weight += weight

        ensemble_score = ensemble_weighted_sum / ensemble_total_weight if ensemble_total_weight > 0 else 0

        # 기본 팩터 가중 점수
        factor_score = (
            value_score * FACTOR_WEIGHTS["value"] +
            growth_score * FACTOR_WEIGHTS["growth"] +
            quality_score * FACTOR_WEIGHTS["quality"] +
            momentum_score * FACTOR_WEIGHTS["momentum"] +
            safety_score * FACTOR_WEIGHTS["safety"] +
            sentiment_score * FACTOR_WEIGHTS["sentiment"] +
            insider_score * FACTOR_WEIGHTS["insider"]
        )

        # ========================================
        # Lynch GARP 보너스
        # ========================================
        lynch_garp_bonus = 0
        lynch_score = investor_scores.get('lynch', 0)
        if lynch_score >= 7:
            lynch_garp_bonus = 0.5
        elif lynch_score >= 5:
            lynch_garp_bonus = 0.25

        # ========================================
        # 전략별 최종 점수 계산
        # ========================================
        fundamental_score = ensemble_score * 0.6 + factor_score * 0.4 + size_bonus + lynch_garp_bonus

        if strategy == "momentum":
            total_score = enhanced_momentum_score
        elif strategy == "hybrid":
            buffett_s = investor_scores.get('buffett', 0)
            graham_s = investor_scores.get('graham', 0)
            drucken_s = investor_scores.get('druckenmiller', 0)

            if buffett_s >= 7 and graham_s >= 6:
                fund_weight, mom_weight = 0.85, 0.15
            elif drucken_s >= 7 and buffett_s < 5 and graham_s < 5:
                fund_weight, mom_weight = 0.55, 0.45
            else:
                fund_weight, mom_weight = 0.70, 0.30

            total_score = fundamental_score * fund_weight + enhanced_momentum_score * mom_weight
        else:
            total_score = fundamental_score

        # ========================================
        # 현금흐름 품질 게이트
        # ========================================
        m_cf = metrics[0] if isinstance(metrics, list) else metrics
        fcf = m_cf.get('free_cash_flow')
        op_cf = m_cf.get('operating_cashflow')
        op_margin = m_cf.get('operating_margin')
        cf_penalty = 0

        if op_cf is not None and op_cf < 0:
            cf_penalty -= 1.5
            all_factors_cf = ["⚠️ 영업CF 마이너스 (본업 현금소진)"]
        elif fcf is not None and fcf < 0:
            cf_penalty -= 1.0
            all_factors_cf = ["⚠️ FCF 마이너스 (높은 CapEx)"]
        else:
            all_factors_cf = []

        if op_margin is not None and 0 < op_margin < 0.05:
            cf_penalty -= 0.5
            all_factors_cf.append(f"⚠️ 영업마진 극저 ({op_margin*100:.1f}%)")

        total_score += cf_penalty

        # 모든 요인 병합
        all_factors = (value_factors + growth_factors + quality_factors +
                      momentum_factors + safety_factors + sentiment_factors +
                      insider_factors + size_factors + all_factors_cf)

        # 예상 수익률 계산
        normalized = (total_score - 3) / 10
        predicted_return = max(-0.30, min(0.40, normalized * 0.35))

        # 신호 결정
        if total_score >= 8:
            signal = "strong_buy"
        elif total_score >= 5:
            signal = "buy"
        elif total_score >= 2:
            signal = "hold"
        elif total_score >= 0:
            signal = "weak_sell"
        else:
            signal = "sell"

        # ========================================
        # 투자자 합의도 분석
        # ========================================
        bullish_investors = [k for k, v in investor_scores.items() if v >= 7]
        bearish_investors = [k for k, v in investor_scores.items() if v <= 3]

        inv_scores_list = list(investor_scores.values())
        if len(inv_scores_list) >= 2:
            investor_std = statistics.stdev(inv_scores_list)
        else:
            investor_std = 0

        consensus_level = "high" if investor_std < 1.5 else ("medium" if investor_std < 2.5 else "low")

        investor_warnings = generate_investor_warnings(ticker, investor_scores, metrics)

        if investor_std > 2.5:
            max_inv = max(investor_scores, key=investor_scores.get)
            min_inv = min(investor_scores, key=investor_scores.get)
            investor_warnings.append(
                f"⚠️ 투자자 의견 분산 심함 (std={investor_std:.1f}): "
                f"{max_inv}({investor_scores[max_inv]:.1f}) vs {min_inv}({investor_scores[min_inv]:.1f})"
            )

        m = metrics[0]
        return {
            "ticker": ticker,
            "total_score": round(total_score, 2),
            "ensemble_score": round(ensemble_score, 2),
            "signal": signal,
            "predicted_return_1y": round(predicted_return * 100, 1),
            "factors": all_factors[:5],
            "strategy": strategy,
            "scores": {
                "value": round(value_score, 1),
                "growth": round(growth_score, 1),
                "quality": round(quality_score, 1),
                "momentum": round(momentum_score, 1),
                "enhanced_momentum": round(enhanced_momentum_score, 1),
                "safety": round(safety_score, 1),
                "sentiment": round(sentiment_score, 1),
                "insider": round(insider_score, 1),
                "size_bonus": round(size_bonus, 1),
                "lynch_garp_bonus": round(lynch_garp_bonus, 2),
                "fundamental": round(fundamental_score, 2),
            },
            "momentum_details": momentum_details,
            "investor_scores": {k: round(v, 1) for k, v in investor_scores.items()},
            "investor_consensus": {
                "bullish": bullish_investors,
                "bearish": bearish_investors,
                "std": round(investor_std, 2),
                "level": consensus_level,
            },
            "investor_warnings": investor_warnings,
            "market_cap": {
                "value": market_cap,
                "display": cap_display,
                "category": cap_category,
            },
            "metrics": {
                "pe": m.get('price_to_earnings_ratio'),
                "pb": m.get('price_to_book_ratio'),
                "roe": round(m.get('return_on_equity', 0) * 100, 1) if m.get('return_on_equity') else None,
                "revenue_growth": round(m.get('revenue_growth', 0) * 100, 1) if m.get('revenue_growth') else None,
                "peg": m.get('peg_ratio'),
            }
        }

    except Exception:
        return None


def run_batch_analysis(tickers, end_date, max_workers=MAX_WORKERS, strategy="fundamental"):
    """배치 분석 실행

    Args:
        tickers: 분석할 종목 리스트
        end_date: 분석 기준일
        max_workers: 병렬 처리 워커 수
        strategy: 분석 전략 (fundamental, momentum, hybrid)
    """
    results = []
    total = len(tickers)
    processed = 0
    lock = threading.Lock()

    strategy_names = {"fundamental": "펀더멘털", "momentum": "모멘텀", "hybrid": "하이브리드"}
    cache_status = "활성화" if CACHE_ENABLED else "비활성화"
    print(f"분석 시작: {total}개 종목 (Workers: {max_workers}, 캐시: {cache_status}, 전략: {strategy_names.get(strategy, strategy)})")

    # 1단계: 가격 데이터 배치 다운로드
    end_dt = datetime.strptime(end_date, "%Y-%m-%d")
    start_dt = end_dt - timedelta(days=90)
    start_date_str = start_dt.strftime("%Y-%m-%d")

    all_prices = batch_fetch_prices(tickers, start_date_str, end_date)

    # 2단계: 재무 지표 선행 수집 (섹터 통계 계산용)
    print(f"📊 섹터 통계 계산을 위한 재무 지표 수집 중... ({total}개 종목)")
    all_metrics = []
    metrics_map = {}

    def fetch_metrics_only(ticker):
        metrics = get_financial_metrics(ticker, end_date, period="annual", limit=2)
        if metrics:
            return ticker, metrics[0]
        return ticker, None

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        for ticker, metrics in executor.map(lambda t: fetch_metrics_only(t), tickers):
            if metrics:
                all_metrics.append(metrics)
                metrics_map[ticker] = metrics

    # 3단계: 섹터별 통계 계산
    sector_stats = calculate_sector_stats(all_metrics)
    sector_count = len([k for k in sector_stats.keys() if not k.startswith('_')])
    print(f"   ✅ {sector_count}개 섹터 통계 계산 완료 (총 {len(all_metrics)}개 종목)")

    # 4단계: 전체 분석
    print(f"📈 투자자 앙상블 분석 중... ({total}개 종목)")
    processed = 0

    def process_with_progress(ticker):
        nonlocal processed
        prefetched_prices = all_prices.get(ticker)
        result = analyze_single_ticker(ticker, end_date, prefetched_prices=prefetched_prices, strategy=strategy, sector_stats=sector_stats)
        with lock:
            processed += 1
            if processed % 25 == 0 or processed == total:
                print(f"   진행: {processed}/{total} ({processed/total*100:.0f}%)")
        return result

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(process_with_progress, t): t for t in tickers}

        for future in as_completed(futures):
            result = future.result()
            if result:
                results.append(result)

    # 점수순 정렬
    results.sort(key=lambda x: x['total_score'], reverse=True)

    # 순위 부여
    for i, r in enumerate(results, 1):
        r['rank'] = i

    return results
