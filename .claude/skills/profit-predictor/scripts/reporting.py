"""
결과 출력 포맷팅

분석 결과를 전략별(펀더멘털/모멘텀/하이브리드) 테이블 형식으로 출력합니다.
투자자 합의도, 철학 불일치 경고, 시가총액별 분포 등 요약 정보도 포함됩니다.
"""


def _format_ticker_name(r):
    """티커와 종목명을 합쳐서 표시 문자열 생성"""
    ticker = r['ticker']
    name = r.get('company_name', '')
    if name and name != ticker:
        # 종목명이 너무 길면 잘라냄
        if len(name) > 14:
            name = name[:13] + "…"
        return f"{ticker}({name})"
    return ticker


def print_results(results, top_n=None, strategy="fundamental"):
    """결과 출력 (전략별 점수 포함). top_n=None이면 전체 출력."""
    strategy_labels = {
        "fundamental": "펀더멘털 분석",
        "momentum": "모멘텀 분석",
        "hybrid": "하이브리드 분석 (펀더멘털 70% + 모멘텀 30%)",
    }

    display_n = min(top_n, len(results)) if top_n else len(results)

    print("\n" + "=" * 160)
    if top_n:
        print(f"📈 TOP {display_n} 매수 추천 종목 ({strategy_labels.get(strategy, strategy)})")
    else:
        print(f"📈 전체 {display_n}개 종목 분석 결과 ({strategy_labels.get(strategy, strategy)})")
    print("=" * 160)

    if strategy == "momentum":
        print(f"{'순위':<4} {'종목':<24} {'시총':<10} {'점수':<6} {'단기M':<7} {'장기M':<7} {'RSI':<6} {'추세':<8} {'신호':<12} {'P/E':<7}")
        print("-" * 160)
    elif strategy == "hybrid":
        print(f"{'순위':<4} {'종목':<24} {'시총':<10} {'점수':<6} {'펀더':<6} {'모멘':<6} {'앙상블':<6} {'신호':<12} {'수익률':<8} {'P/E':<7} {'ROE':<7} {'강세 투자자':<20}")
        print("-" * 160)
    else:  # fundamental
        print(f"{'순위':<4} {'종목':<24} {'시총':<10} {'점수':<6} {'앙상블':<6} {'신호':<12} {'수익률':<8} {'P/E':<7} {'ROE':<7} {'강세 투자자':<20} {'주요 요인'}")
        print("-" * 160)

    for r in results[:display_n]:
        pe_str = f"{r['metrics']['pe']:.1f}" if r['metrics']['pe'] else "N/A"
        roe_str = f"{r['metrics']['roe']:.0f}%" if r['metrics']['roe'] else "N/A"
        cap_str = r.get('market_cap', {}).get('display', 'N/A')
        factors_str = ', '.join(r['factors'][:2]) if r['factors'] else '-'

        bullish = r.get('investor_consensus', {}).get('bullish', [])
        bullish_str = ', '.join(bullish[:3]) if bullish else '-'

        ensemble_str = f"{r.get('ensemble_score', 0):.1f}"
        fund_str = f"{r.get('scores', {}).get('fundamental', 0):.1f}"
        mom_str = f"{r.get('scores', {}).get('enhanced_momentum', 0):.1f}"

        mom_details = r.get('momentum_details', {})
        short_m = f"{mom_details.get('short_momentum', 0):+.0f}%"
        long_m = f"{mom_details.get('long_momentum', 0):+.0f}%"
        rsi_str = f"{mom_details.get('rsi', 50):.0f}"
        trend_map = {"bullish": "📈상승", "bearish": "📉하락", "neutral": "➡️중립"}
        trend_str = trend_map.get(mom_details.get('trend', 'neutral'), '➡️중립')

        signal_display = {
            "strong_buy": "🟢 강력매수",
            "buy": "🔵 매수",
            "hold": "⚪ 보유",
            "weak_sell": "🟡 약한매도",
            "sell": "🔴 매도"
        }.get(r['signal'], r['signal'])

        ticker_name = _format_ticker_name(r)

        if strategy == "momentum":
            print(f"{r['rank']:<4} {ticker_name:<24} {cap_str:<10} {r['total_score']:<6.2f} {short_m:<7} {long_m:<7} {rsi_str:<6} {trend_str:<8} {signal_display:<12} {pe_str:<7}")
        elif strategy == "hybrid":
            print(f"{r['rank']:<4} {ticker_name:<24} {cap_str:<10} {r['total_score']:<6.2f} {fund_str:<6} {mom_str:<6} {ensemble_str:<6} {signal_display:<12} {r['predicted_return_1y']:>+5.1f}%   {pe_str:<7} {roe_str:<7} {bullish_str:<20}")
        else:  # fundamental
            print(f"{r['rank']:<4} {ticker_name:<24} {cap_str:<10} {r['total_score']:<6.2f} {ensemble_str:<6} {signal_display:<12} {r['predicted_return_1y']:>+5.1f}%   {pe_str:<7} {roe_str:<7} {bullish_str:<20} {factors_str[:35]}")

    # 통계 출력
    buy_signals = [r for r in results if r['signal'] in ['strong_buy', 'buy']]
    sell_signals = [r for r in results if r['signal'] in ['weak_sell', 'sell']]

    cap_categories = {"mega": [], "large": [], "mid": [], "small": [], None: []}
    for r in buy_signals:
        cat = r.get('market_cap', {}).get('category')
        cap_categories[cat].append(r)

    print("\n" + "=" * 130)
    print(f"📊 분석 요약")
    print(f"   - 총 분석 종목: {len(results)}개")
    print(f"   - 매수 추천 (strong_buy + buy): {len(buy_signals)}개")
    print(f"   - 매도/회피 권장: {len(sell_signals)}개")
    if buy_signals:
        avg_return = sum(r['predicted_return_1y'] for r in buy_signals) / len(buy_signals)
        avg_ensemble = sum(r.get('ensemble_score', 0) for r in buy_signals) / len(buy_signals)
        print(f"   - 매수 추천 종목 평균 예상 수익률: {avg_return:+.1f}%")
        print(f"   - 매수 추천 종목 평균 앙상블 점수: {avg_ensemble:.2f}")

    # 투자자 합의도 분석
    display_results = results[:display_n]
    consensus_counts = {"high": 0, "medium": 0, "low": 0}
    for r in display_results:
        level = r.get('investor_consensus', {}).get('level', 'medium')
        consensus_counts[level] = consensus_counts.get(level, 0) + 1
    if consensus_counts["low"] > 0:
        low_consensus = [_format_ticker_name(r) for r in display_results if r.get('investor_consensus', {}).get('level') == 'low']
        label = f"상위 {display_n}개" if top_n else f"전체 {display_n}개"
        print(f"\n🔍 투자자 합의도 분석 ({label})")
        print(f"   - 높은 합의 (std<1.5): {consensus_counts['high']}개")
        print(f"   - 보통 합의 (std<2.5): {consensus_counts['medium']}개")
        print(f"   - 낮은 합의 (std≥2.5): {consensus_counts['low']}개 → {', '.join(low_consensus[:8])}")

    # 투자자별 강세 종목 분석
    print(f"\n👥 투자자별 강세 종목 (점수 ≥ 7)")
    investor_picks = {}
    for r in results[:50]:
        for investor in r.get('investor_consensus', {}).get('bullish', []):
            if investor not in investor_picks:
                investor_picks[investor] = []
            investor_picks[investor].append(_format_ticker_name(r))

    investor_names = {
        "buffett": "Warren Buffett",
        "lynch": "Peter Lynch",
        "graham": "Ben Graham",
        "druckenmiller": "Druckenmiller",
        "fisher": "Phil Fisher",
    }

    for inv_key, inv_name in investor_names.items():
        picks = investor_picks.get(inv_key, [])
        if picks:
            print(f"   - {inv_name}: {', '.join(picks[:5])}" + (f" 외 {len(picks)-5}개" if len(picks) > 5 else ""))

    # 투자 철학 불일치 경고
    warnings_found = []
    for r in display_results:
        warnings = r.get('investor_warnings', [])
        if warnings:
            warnings_found.append((_format_ticker_name(r), warnings))

    if warnings_found:
        print(f"\n⚠️ 투자 철학 불일치 경고 (알고리즘 vs 실제 투자자)")
        print(f"   (알고리즘 점수가 높지만 실제 투자자 철학과 충돌 가능성)")
        for ticker_name, warnings in warnings_found[:10]:
            for w in warnings:
                print(f"   - {ticker_name}: {w}")

    # 시가총액별 매수 추천 분포
    print(f"\n📏 시가총액별 매수 추천 분포")
    cap_labels = {"mega": "메가캡 (>$200B)", "large": "대형주 ($10B-$200B)", "mid": "중형주 ($2B-$10B)", "small": "소형주 (<$2B)"}
    for cat, label in cap_labels.items():
        count = len(cap_categories.get(cat, []))
        if count > 0:
            tickers = ', '.join([_format_ticker_name(r) for r in cap_categories[cat][:5]])
            suffix = f" 외 {count-5}개" if count > 5 else ""
            print(f"   - {label}: {count}개 ({tickers}{suffix})")
