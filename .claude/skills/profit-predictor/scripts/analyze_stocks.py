#!/usr/bin/env python3
"""
Stock Analyzer - End-to-End 종목 분석 및 순위 산정 (Yahoo Finance + DART/PyKRX)

사용법:
    # 특정 종목 분석
    python analyze_stocks.py --tickers AAPL,GOOGL,MSFT,NVDA,TSLA

    # S&P 500 전체 분석 (--top 생략 시 전체 종목 분석)
    python analyze_stocks.py --index sp500

    # S&P 500 상위 30개만 분석
    python analyze_stocks.py --index sp500 --top 30

    # KOSPI 시가총액 상위 30개 분석
    python analyze_stocks.py --index kospi --top 30

    # KOSDAQ 150 분석
    python analyze_stocks.py --index kosdaq150

    # KRX 전체 (KOSPI + KOSDAQ) 분석
    python analyze_stocks.py --index krx

    # 결과를 파일로 저장
    python analyze_stocks.py --index sp500 --output results.json

    # 캐시 없이 실행
    python analyze_stocks.py --index sp500 --no-cache

    # 캐시 삭제
    python analyze_stocks.py --clear-cache

    # Wikipedia/PyKRX에서 최신 티커 목록 갱신
    python analyze_stocks.py --index sp500 --update-tickers
"""
import sys
import json
import argparse
from datetime import datetime

import config
from cache import clear_cache, get_cache_stats, cache_stats
from data_fetcher import get_index_tickers, sort_tickers_by_market_cap
from analysis import run_batch_analysis
from reporting import print_results
from ticker_utils import is_korean_index, is_korean_ticker


def main():
    parser = argparse.ArgumentParser(
        description="종목 분석 및 1년 후 수익률 예측",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
예시:
  # 특정 종목 분석
  uv run python analyze_stocks.py --tickers AAPL,GOOGL,MSFT

  # S&P 500 전체 분석 (--top 미지정 시 전체)
  uv run python analyze_stocks.py --index sp500

  # NASDAQ 100 상위 20개만 분석
  uv run python analyze_stocks.py --index nasdaq100 --top 20

  # KOSPI 시가총액 상위 30개 분석
  uv run python analyze_stocks.py --index kospi --top 30

  # KOSDAQ 150 전체 분석
  uv run python analyze_stocks.py --index kosdaq150

  # KRX 전체 (KOSPI + KOSDAQ) 분석
  uv run python analyze_stocks.py --index krx

  # 한국 특정 종목 분석 (삼성전자, SK하이닉스)
  uv run python analyze_stocks.py --tickers 005930,000660

  # 결과 저장
  uv run python analyze_stocks.py --index sp500 --output results.json
        """
    )
    parser.add_argument("--tickers", type=str, help="분석할 종목 (콤마 구분)")
    parser.add_argument("--index", type=str, choices=["sp500", "nasdaq100", "kospi", "kosdaq", "kospi200", "kosdaq150", "krx"], help="인덱스 전체 분석 (krx = KOSPI200+KOSDAQ150 대표 종목)")
    parser.add_argument("--top", type=int, default=None, help="분석 대상 종목 수 제한 (미지정 시 전체 종목 분석)")
    parser.add_argument("--strategy", type=str, default="hybrid",
                       choices=["fundamental", "momentum", "hybrid"],
                       help="분석 전략: fundamental(펀더멘털), momentum(모멘텀), hybrid(혼합) (기본: hybrid)")
    parser.add_argument("--no-sort-by-cap", action="store_false", dest="sort_by_cap",
                       help="시가총액 정렬 비활성화 (기본: 시가총액 내림차순 정렬)")
    parser.set_defaults(sort_by_cap=True)
    parser.add_argument("--workers", type=int, default=config.MAX_WORKERS, help=f"병렬 처리 워커 수 (기본: {config.MAX_WORKERS})")
    parser.add_argument("--output", type=str, help="결과 저장 파일 (JSON)")
    parser.add_argument("--period", type=str, default=config.DEFAULT_PERIOD, help="예측 기간 (기본: 1Y)")
    parser.add_argument("--no-cache", action="store_true", help="캐시 사용 안 함 (항상 API 호출)")
    parser.add_argument("--clear-cache", action="store_true", help="캐시 삭제 후 종료")
    parser.add_argument("--cache-stats", action="store_true", help="캐시 통계 출력 후 종료")
    parser.add_argument("--update-tickers", action="store_true", help="Wikipedia/PyKRX에서 최신 티커 목록 갱신")

    args = parser.parse_args()

    # 캐시 관련 명령 처리
    if args.clear_cache:
        clear_cache()
        sys.exit(0)

    if args.cache_stats:
        stats = get_cache_stats()
        print(f"\n📦 캐시 통계")
        print(f"   - 캐시 파일 수: {stats['total_files']}개")
        print(f"   - 캐시 크기: {stats['total_size_mb']} MB")
        print(f"   - 캐시된 날짜: {', '.join(stats['dates'][:5]) if stats['dates'] else '없음'}")
        sys.exit(0)

    # 캐시 비활성화
    if args.no_cache:
        config.CACHE_ENABLED = False
        print("⚠️  캐시 비활성화됨 - 모든 데이터를 API에서 가져옵니다.")

    # 종목 리스트 결정
    if args.tickers:
        tickers = [t.strip() for t in args.tickers.split(',')]
    elif args.index:
        use_ticker_cache = config.CACHE_ENABLED and not args.update_tickers
        tickers = get_index_tickers(args.index, use_cache=use_ticker_cache)
    else:
        print("오류: --tickers 또는 --index 중 하나를 지정해야 합니다.")
        parser.print_help()
        sys.exit(1)

    # 시가총액 기준 정렬 (기본값: 활성화, --no-sort-by-cap으로 비활성화)
    if args.sort_by_cap and tickers:
        tickers = sort_tickers_by_market_cap(tickers, top_n=args.top if args.top else 0)
    elif args.top and len(tickers) > args.top:
        tickers = tickers[:args.top]

    end_date = datetime.now().strftime("%Y-%m-%d")
    strategy_names = {"fundamental": "펀더멘털", "momentum": "모멘텀", "hybrid": "하이브리드"}

    # 데이터 소스 자동 감지
    is_kr = (args.index and is_korean_index(args.index)) or (args.tickers and all(is_korean_ticker(t.strip()) for t in args.tickers.split(',')))
    data_source = "DART + PyKRX" if is_kr else "Yahoo Finance"

    print(f"\n{'='*60}")
    print(f"🔍 AI Hedge Fund - 종목 분석 시스템 ({data_source})")
    print(f"{'='*60}")
    print(f"분석 날짜: {end_date}")
    print(f"예측 기간: {args.period}")
    print(f"분석 전략: {strategy_names.get(args.strategy, args.strategy)}")
    print(f"대상 종목: {len(tickers)}개")
    print()

    # 분석 실행
    results = run_batch_analysis(tickers, end_date, args.workers, strategy=args.strategy)

    if not results:
        print("분석 결과가 없습니다.")
        sys.exit(1)

    # 결과 출력
    print_results(results, args.top, strategy=args.strategy)

    # 캐시 통계 출력
    if config.CACHE_ENABLED:
        total_requests = cache_stats["hits"] + cache_stats["misses"]
        if total_requests > 0:
            hit_rate = cache_stats["hits"] / total_requests * 100
            print(f"\n💾 캐시 통계: {cache_stats['hits']}/{total_requests} 히트 ({hit_rate:.0f}%), API 호출 {cache_stats['misses']}회 절감")

    # 파일 저장
    strategy_methods = {
        "fundamental": "Ensemble multi-factor analysis (Value + Growth + Quality + Momentum + Safety)",
        "momentum": "Enhanced momentum analysis (Short/Long momentum + RSI + Trend)",
        "hybrid": "Hybrid analysis (70% Fundamental + 30% Enhanced Momentum, Lynch GARP bonus)",
    }
    if args.output:
        output_data = {
            "analysis_date": end_date,
            "prediction_period": args.period,
            "strategy": args.strategy,
            "total_analyzed": len(results),
            "methodology": strategy_methods.get(args.strategy, "Multi-factor analysis"),
            "factor_weights": config.FACTOR_WEIGHTS,
            "rankings": results
        }
        with open(args.output, 'w', encoding='utf-8') as f:
            json.dump(output_data, f, indent=2, ensure_ascii=False)
        print(f"\n결과 저장됨: {args.output}")


if __name__ == "__main__":
    main()
