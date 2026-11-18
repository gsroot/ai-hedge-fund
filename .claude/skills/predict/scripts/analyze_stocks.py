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
from datetime import UTC, datetime

import config
from cache import clear_cache, get_cache_stats, cache_stats
# get_index_tickers는 backtesting/backtest.py가 이 모듈에서 import하므로 다시 내보낸다.
from data_fetcher import get_index_tickers, resolve_index_universe, sort_tickers_by_market_cap  # noqa: F401
from analysis import analyze_single_ticker, run_batch_analysis_with_exclusions, summarize_exclusions  # noqa: F401
from factor_evidence import default_factor_weight_policy, load_factor_weight_policy_safe
from provider_readiness import load_provider_readiness_policy
from reporting import print_results
from research_ranking import OBSERVED_FACTOR_SPEC_ID, RANKING_POLICY_ID, build_research_shortlist
from ticker_utils import is_korean_index, is_korean_ticker, normalize_korean_ticker


def research_factor_policy(evidence_path, market_scope, index, end_date):
    """Legacy evidence remains auditable; the new observation/coverage rules require new PIT validation."""
    policy = default_factor_weight_policy(config.FACTOR_WEIGHTS)
    policy.update(factor_spec_id=OBSERVED_FACTOR_SPEC_ID, fallback_reason="observed_factor_pit_validation_pending")
    if evidence_path:
        legacy = load_factor_weight_policy_safe(
            config.FACTOR_WEIGHTS, evidence_path, market_scope=market_scope, index=index, analysis_date=end_date
        )
        policy["submitted_evidence"] = {
            key: legacy.get(key) for key in ("source", "mode", "validation_end", "fallback_reason", "evidence_error")
        }
        policy["submitted_evidence"]["applied_to_ranking"] = False
    return policy


def main():
    parser = argparse.ArgumentParser(
        description="다중 팩터 기반 종목 분석 및 순위 산정",
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
    parser.add_argument("--display", type=int, default=None, help="화면에 표시할 상위 종목 수 (분석 대상 수와 독립)")
    parser.add_argument("--strategy", type=str, default="hybrid",
                       choices=["fundamental", "momentum", "hybrid"],
                       help="분석 전략: fundamental(펀더멘털), momentum(모멘텀), hybrid(혼합) (기본: hybrid)")
    parser.add_argument("--no-sort-by-cap", action="store_false", dest="sort_by_cap",
                       help="시가총액 정렬 비활성화 (기본: 시가총액 내림차순 정렬)")
    parser.set_defaults(sort_by_cap=True)
    parser.add_argument("--workers", type=int, default=config.MAX_WORKERS, help=f"병렬 처리 워커 수 (기본: {config.MAX_WORKERS})")
    parser.add_argument("--output", type=str, help="결과 저장 파일 (JSON)")
    parser.add_argument("--period", type=str, default="1Y", choices=["1Y"],
                        help="점수 비교 기간 라벨 (현재 1Y만 지원, 실제 수익률 예측 아님)")
    parser.add_argument("--no-cache", action="store_true", help="캐시 사용 안 함 (항상 API 호출)")
    parser.add_argument("--clear-cache", action="store_true", help="캐시 삭제 후 종료")
    parser.add_argument("--cache-stats", action="store_true", help="캐시 통계 출력 후 종료")
    parser.add_argument("--update-tickers", action="store_true", help="Wikipedia/PyKRX에서 최신 티커 목록 갱신")
    parser.add_argument(
        "--factor-evidence-json",
        help=(
            "기존 PIT 팩터 근거의 호환성 감사. 새 순위는 새 입력 계약의 검증까지 prior_only 사용"
        ),
    )
    parser.add_argument(
        "--provider-readiness-json",
        help=(
            "provider_readiness_v1 표본 감사 JSON. 미지정 시 provider 상태를 "
            "not_provided로 기록하고 missing evidence를 0으로 취급하지 않음"
        ),
    )

    args = parser.parse_args()
    if any(value is not None and value <= 0 for value in (args.top, args.display, args.workers)):
        parser.error("--top, --display, --workers는 양수여야 합니다.")
    if args.tickers and args.index:
        parser.error("--index와 --tickers 중 하나를 선택하세요.")

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
        symbols = [t.strip().upper() for t in args.tickers.split(',') if t.strip()]
        tickers = list(dict.fromkeys(normalize_korean_ticker(t) if is_korean_ticker(t) else t for t in symbols))
        if not tickers:
            parser.error("분석할 종목을 입력하세요.")
        universe_source, universe_may_be_stale = "explicit_tickers", False
        universe_size = len(tickers)
    elif args.index:
        use_ticker_cache = config.CACHE_ENABLED and not args.update_tickers
        universe = resolve_index_universe(args.index, use_cache=use_ticker_cache)
        tickers = list(universe.tickers)
        universe_source, universe_may_be_stale = universe.source, universe.may_be_stale
        universe_size = len(universe.tickers)
    else:
        print("오류: --tickers 또는 --index 중 하나를 지정해야 합니다.")
        parser.print_help()
        sys.exit(1)

    # 시가총액 기준 정렬 (기본값: 활성화, --no-sort-by-cap으로 비활성화)
    mixed = bool(args.tickers and len({is_korean_ticker(t) for t in tickers}) > 1)
    is_kr = is_korean_index(args.index) if args.index else all(is_korean_ticker(t) for t in tickers)
    selection = None
    if mixed and args.sort_by_cap and args.top and args.top < len(tickers):
        parser.error("혼합 통화 시가총액은 직접 비교할 수 없습니다. --top을 생략하거나 --no-sort-by-cap을 사용하세요.")
    if args.sort_by_cap and args.top and args.top < len(tickers):
        missing_caps = []
        tickers = sort_tickers_by_market_cap(tickers, top_n=args.top, unavailable=missing_caps)
        selection = {"limit": args.top, "eligible_count": universe_size - len(missing_caps),
                     "missing_cap_tickers": sorted(missing_caps),
                     "scope": "observed_caps_only" if missing_caps else "all_requested_caps"}
    elif args.top and len(tickers) > args.top:
        tickers = tickers[:args.top]

    end_date = datetime.now(UTC).date().isoformat()
    strategy_names = {"fundamental": "펀더멘털", "momentum": "모멘텀", "hybrid": "하이브리드"}

    # 데이터 소스 자동 감지
    data_source = ("DART / FDR / PyKRX 및 Yahoo Finance / financial-datasets" if mixed else
                   "DART / FDR / PyKRX" if is_kr else "Yahoo Finance / financial-datasets")
    try:
        factor_weight_policy = research_factor_policy(
            args.factor_evidence_json, "mixed" if mixed else "krx" if is_kr else "us", args.index or "custom", end_date
        )
        markets = ["krx", "sp500"] if mixed else ["krx" if is_kr else "sp500"]
        readiness = {market: load_provider_readiness_policy(args.provider_readiness_json, market_scope=market,
                                                            analysis_date=end_date) for market in markets}
        provider_readiness_policy = readiness[markets[0]]
        if mixed:
            all_ready = all(item["all_samples_ready"] for item in readiness.values())
            provider_readiness_policy = {
                "contract_id": "provider_readiness_v1", "market_scope": "mixed", "markets": readiness,
                "mode": provider_readiness_policy["mode"], "all_samples_ready": all_ready,
                "ranking_policy": "provider_ready_but_point_in_time_contract_still_required" if all_ready else
                                  "missing_evidence_requires_prior_or_explanation_only",
            }
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        parser.error(f"증거 JSON을 적용할 수 없습니다: {exc}")
    effective_factor_weights = factor_weight_policy["effective_weights"]

    print(f"\n{'='*60}")
    print(f"🔍 AI Hedge Fund - 종목 분석 시스템 ({data_source})")
    print(f"{'='*60}")
    print(f"분석 날짜: {end_date}")
    print(f"평가 기간 라벨: {args.period} (점수 기반, 수익률 예측 아님)")
    print(f"분석 전략: {strategy_names.get(args.strategy, args.strategy)}")
    print(f"팩터 가중치 정책: {factor_weight_policy['mode']}")
    print(f"대상 종목: {len(tickers)}개")
    stale_note = " ⚠️ 현재 구성 종목과 다를 수 있음" if universe_may_be_stale else ""
    print(f"유니버스 출처: {universe_source}{stale_note}")
    print()

    # 분석 실행
    batch = run_batch_analysis_with_exclusions(
        tickers,
        end_date,
        args.workers,
        strategy=args.strategy,
        factor_weights=effective_factor_weights,
    )
    results = list(batch.results)

    # 결과 출력
    if results:
        print_results(results, args.display, strategy=args.strategy)

    # 캐시 통계 출력
    if config.CACHE_ENABLED:
        total_requests = cache_stats["hits"] + cache_stats["misses"]
        if total_requests > 0:
            hit_rate = cache_stats["hits"] / total_requests * 100
            print(f"\n💾 캐시 통계: {cache_stats['hits']}/{total_requests} 히트 ({hit_rate:.0f}%), API 호출 {cache_stats['misses']}회 절감")

    # 파일 저장
    strategy_methods = {
        "fundamental": "Within-universe observed financial and insider factor percentiles",
        "momentum": "Price-only enhanced momentum (60 dated closes, RSI and trend)",
        "hybrid": "Within-universe observed financial, insider and price momentum factor percentiles",
    }
    if args.output:
        output_data = {
            "analysis_date": end_date,
            "available_at": datetime.now(UTC).isoformat(),
            "index": args.index or "custom",
            "evaluation_horizon": args.period,
            "return_estimate": {
                "calibrated": False,
                "method": "heuristic_score_mapping",
                "label": "점수 환산값(예상수익률 아님)",
            },
            "strategy": args.strategy,
            "ranking_policy_id": RANKING_POLICY_ID,
            "provider_routes": data_source,
            "market_cap_selection": selection,
            "research_shortlist": build_research_shortlist(results),
            "universe": {
                "source": universe_source,
                "may_be_stale": universe_may_be_stale,
                "size": universe_size,
                "requested_count": len(tickers),
            },
            "total_requested": len(tickers),
            "total_analyzed": len(results),
            "total_excluded": len(batch.excluded),
            "exclusion_summary": summarize_exclusions(batch.excluded),
            "excluded": list(batch.excluded),
            "methodology": strategy_methods.get(args.strategy, "Multi-factor analysis"),
            "factor_weights": effective_factor_weights,
            "factor_weight_policy": factor_weight_policy,
            "provider_readiness_policy": provider_readiness_policy,
            "news_sentiment_policy": {
                "classifier_policy_id": "news_event_v2",
                "ranking_policy": "risk_and_explanation_only",
                "ranking_contribution_applied": False,
                "base_sentiment_factor_weight": effective_factor_weights["sentiment"],
                "effective_sentiment_factor_weight": 0.0,
                "accuracy_validated": False,
                "note": (
                    "keyword sentiment is stored as diagnostics; the ranking score "
                    "stays neutral until all validation gates pass"
                ),
            },
            "rankings": results
        }
        with open(args.output, 'w', encoding='utf-8') as f:
            json.dump(output_data, f, indent=2, ensure_ascii=False)
        print(f"\n결과 저장됨: {args.output}")

    # 전부 제외된 실행도 excluded·universe 기록은 남긴 뒤 실패로 종료한다.
    if not results:
        print("분석 결과가 없습니다.")
        sys.exit(1)


if __name__ == "__main__":
    main()
