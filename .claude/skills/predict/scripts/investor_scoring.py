"""
투자자 스타일별 점수 계산

5명의 전설적 투자자(Buffett, Lynch, Graham, Fisher, Druckenmiller)의
투자 철학을 정량화한 점수를 계산합니다. 섹터별 통계 계산 및
투자 철학 불일치 경고 기능도 포함됩니다.
"""
import statistics
from collections import defaultdict


# ============================================================================
# 섹터별 통계 계산 (상대적 밸류에이션용)
# ============================================================================

def calculate_sector_stats(all_metrics: list) -> dict:
    """
    모든 종목의 섹터별 평균/중간값 계산

    Returns:
        dict: {
            'Technology': {'pe_median': 25, 'pe_avg': 28, ...},
            '_market': {...}  # 전체 시장 통계
        }
    """
    sector_data = defaultdict(lambda: {'pe': [], 'pb': [], 'peg': [], 'roe': [], 'growth': [], 'momentum': []})

    for m in all_metrics:
        if not m:
            continue
        sector = m.get('sector') or '_unknown'

        pe = m.get('price_to_earnings_ratio')
        if pe and 0 < pe < 500:
            sector_data[sector]['pe'].append(pe)
            sector_data['_market']['pe'].append(pe)

        pb = m.get('price_to_book_ratio')
        if pb and 0 < pb < 50:
            sector_data[sector]['pb'].append(pb)
            sector_data['_market']['pb'].append(pb)

        peg = m.get('peg_ratio')
        if peg and -5 < peg < 10:
            sector_data[sector]['peg'].append(peg)
            sector_data['_market']['peg'].append(peg)

        roe = m.get('return_on_equity')
        if roe and -1 < roe < 2:
            sector_data[sector]['roe'].append(roe)
            sector_data['_market']['roe'].append(roe)

        growth = m.get('revenue_growth')
        if growth and -1 < growth < 3:
            sector_data[sector]['growth'].append(growth)
            sector_data['_market']['growth'].append(growth)

    result = {}
    for sector, data in sector_data.items():
        result[sector] = {}
        for metric, values in data.items():
            if len(values) >= 3:
                result[sector][f'{metric}_median'] = statistics.median(values)
                result[sector][f'{metric}_avg'] = statistics.mean(values)
                result[sector][f'{metric}_std'] = statistics.stdev(values) if len(values) > 1 else 0
                result[sector][f'{metric}_p25'] = sorted(values)[len(values) // 4] if len(values) >= 4 else min(values)
                result[sector][f'{metric}_p75'] = sorted(values)[3 * len(values) // 4] if len(values) >= 4 else max(values)
                result[sector][f'{metric}_count'] = len(values)

    return result


def get_percentile_rank(value: float, values: list) -> float:
    """값이 리스트에서 몇 번째 백분위인지 계산 (0-100)"""
    if not values or value is None:
        return 50
    sorted_vals = sorted(values)
    count_below = sum(1 for v in sorted_vals if v < value)
    return (count_below / len(sorted_vals)) * 100


# ============================================================================
# Warren Buffett 스타일 점수
# ============================================================================

def calculate_buffett_score(metrics, growth_score, quality_score, safety_score) -> float:
    """
    Warren Buffett 스타일 점수 (moat + margin of safety)

    평가 구조:
    1. 핵심 재무 지표: ROE > 15%, 낮은 부채, 영업 마진 > 15%
    2. 산업별 조정: 원자재/에너지 hard cap (최대 5점), 소비재 독점 가산점
    3. 밸류에이션: P/E 기반 안전마진 체크
    4. 수익 일관성: 적자 감점, 자본잠식 기업 hard cap (최대 3점)
    """
    if not metrics:
        return 0

    m = metrics[0] if isinstance(metrics, list) else metrics
    score = 0

    # 1. 핵심 재무 지표
    roe = m.get('return_on_equity')
    if roe and roe > 0.15:
        score += 3
    elif roe and roe > 0.10:
        score += 1

    de = m.get('debt_to_equity')
    is_negative_equity = False
    if de is not None and de < 0.5 and de >= 0:
        score += 2
    elif de is not None and de < 0:
        score -= 2
        is_negative_equity = True

    op_margin = m.get('operating_margin')
    if op_margin and op_margin > 0.15:
        score += 2

    score += quality_score * 0.2 + safety_score * 0.1

    # 2. 산업별 조정
    sector = m.get('sector')

    BUFFETT_AVOID_SECTORS = ['Basic Materials', 'Energy']
    if sector in BUFFETT_AVOID_SECTORS:
        score = min(score * 0.6, 5.0)

    BUFFETT_PREFER_SECTORS = ['Consumer Defensive', 'Financial Services', 'Healthcare']
    if sector in BUFFETT_PREFER_SECTORS:
        score += 0.8
    if sector == 'Technology' and roe and roe > 0.25 and op_margin and op_margin > 0.25:
        score += 0.5

    # 3. 밸류에이션 체크
    pe = m.get('price_to_earnings_ratio')
    if pe and pe > 0:
        if pe > 50:
            score -= 2
        elif pe > 35:
            score -= 1
        elif pe < 15:
            score += 1

    # 4. 수익 일관성 체크
    net_income = m.get('net_income')
    if net_income and net_income < 0:
        score -= 2

    if is_negative_equity:
        score = min(score, 3.0)

    return min(10, max(0, score))


# ============================================================================
# Peter Lynch 스타일 점수
# ============================================================================

def calculate_lynch_score(metrics, growth_score, sentiment_score, insider_score, sector_stats=None) -> float:
    """
    Peter Lynch 스타일 점수 (GARP + PEG)

    점수 구조 (최대 10점):
    - 상대적 PEG: 최대 4점 (섹터 대비 저평가)
    - GARP 비율: 최대 2.5점 (성장률/P/E)
    - 성장 가중치: 최대 3점 (Lynch의 핵심!)
    - 수익 안정성 + 배당: 최대 2점
    - 10배 가능성: 최대 1.5점
    - 내부자/센티먼트: 최대 1점
    """
    if not metrics:
        return 0

    m = metrics[0] if isinstance(metrics, list) else metrics
    score = 0

    peg = m.get('peg_ratio')
    sector = m.get('sector') or '_market'
    rev_growth = m.get('revenue_growth')
    earnings_growth = m.get('earnings_growth')
    pe = m.get('price_to_earnings_ratio')

    # PEG가 없으면 직접 계산
    if not peg and pe and pe > 0:
        growth_rate = earnings_growth or rev_growth
        if growth_rate and growth_rate > 0:
            peg = pe / (growth_rate * 100)

    # 1. 상대적 PEG 평가 (섹터 대비)
    if peg and sector_stats:
        sector_peg_median = sector_stats.get(sector, {}).get('peg_median') or sector_stats.get('_market', {}).get('peg_median')
        if sector_peg_median and sector_peg_median > 0:
            peg_ratio_to_sector = peg / sector_peg_median
            if peg_ratio_to_sector < 0.5:
                score += 4
            elif peg_ratio_to_sector < 0.7:
                score += 3
            elif peg_ratio_to_sector < 0.9:
                score += 2
            elif peg_ratio_to_sector < 1.1:
                score += 1
    if peg:
        if 0 < peg < 0.5:
            score += 1.5
        elif 0 < peg < 1:
            score += 1

    # 2. GARP 본질: 성장률 대비 밸류에이션 균형
    if pe and pe > 0:
        growth_rate = max(rev_growth or 0, earnings_growth or 0)
        if growth_rate > 0:
            garp_ratio = (growth_rate * 100) / pe
            if garp_ratio > 2.0:
                score += 2.5
            elif garp_ratio > 1.5:
                score += 2
            elif garp_ratio > 1.0:
                score += 1.5
            elif garp_ratio > 0.5:
                score += 0.5

    # 3. 성장 점수 반영
    score += growth_score * 0.3

    # 4. 수익 안정성 + 배당 콤보
    roe = m.get('return_on_equity')
    op_margin = m.get('operating_margin')
    div_yield = m.get('dividend_yield')

    if roe and roe > 0.15 and op_margin and op_margin > 0.10:
        score += 1
    elif roe and roe > 0.10 and op_margin and op_margin > 0.05:
        score += 0.5

    if div_yield and div_yield > 0 and rev_growth and rev_growth > 0:
        total_return_est = div_yield + rev_growth
        if total_return_est > 0.15:
            score += 1
        elif total_return_est > 0.08:
            score += 0.5

    # 5. 매출 성장 직접 반영
    if rev_growth:
        if rev_growth > 0.25:
            score += 1
        elif rev_growth > 0.10:
            score += 0.5

    # 6. "10배 가능성" 가점
    if rev_growth and rev_growth > 0.20:
        if peg and 0 < peg < 1.5:
            score += 1.5
        elif peg and 0 < peg < 2:
            score += 0.5

    # 7. 내부자 활동
    score += insider_score * 0.1

    # 8. 매출 트렌드 체크 - "떨어지는 칼" 감지
    if rev_growth is not None:
        if rev_growth < -0.20:
            score -= 2.5
        elif rev_growth < -0.10:
            score -= 1.5

    # 9. 시가총액 기반 조정
    market_cap = m.get('market_cap')
    if market_cap:
        if market_cap > 200e9:
            score -= 0.8
        elif market_cap > 100e9:
            score -= 0.3
        elif market_cap < 10e9:
            score += 0.5
        elif market_cap < 2e9:
            score += 1.0

    # 10. 경기순환주 사이클 위치 조정
    CYCLICAL_SECTORS = ['Basic Materials', 'Energy', 'Industrials']
    if sector in CYCLICAL_SECTORS:
        if peg and peg < 0.5 and rev_growth and rev_growth < 0:
            score -= 1.5
        score -= 0.5

    return min(10, max(0, score))


# ============================================================================
# Ben Graham 스타일 점수
# ============================================================================

def calculate_graham_score(metrics, sector_stats=None) -> float:
    """
    Ben Graham 스타일 점수 (Deep Value)

    평가 구조:
    - A. 밸류에이션 (~50%): P/E < 15, P/B < 1.5, Graham Number, EV/EBITDA
    - B. 재무 건전성 (~30%): 유동비율 > 2, 낮은 부채, FCF Yield
    - C. 수익 안정성 + 배당 (~20%): 배당 수익률, ROE 안정성, 이익률
    """
    if not metrics:
        return 0

    m = metrics[0] if isinstance(metrics, list) else metrics
    score = 0

    pe = m.get('price_to_earnings_ratio')
    pb = m.get('price_to_book_ratio')
    sector = m.get('sector') or '_market'

    # A. 밸류에이션
    if pe and pe > 0 and sector_stats:
        sector_pe_median = sector_stats.get(sector, {}).get('pe_median') or sector_stats.get('_market', {}).get('pe_median')
        if sector_pe_median and sector_pe_median > 0:
            pe_discount = 1 - (pe / sector_pe_median)
            if pe_discount > 0.5:
                score += 3
            elif pe_discount > 0.3:
                score += 2.5
            elif pe_discount > 0.15:
                score += 1.5
            elif pe_discount > 0:
                score += 1
            elif pe_discount > -0.15:
                score += 0.5
        elif pe:
            if 0 < pe < 10:
                score += 3
            elif 0 < pe < 15:
                score += 2
            elif 0 < pe < 25:
                score += 0.5

    if pb and pb > 0:
        if 0 < pb < 1:
            score += 2
        elif 0 < pb < 1.5:
            score += 1.5
        elif 0 < pb < 3:
            score += 0.5

    if pe and pb and pe > 0 and pb > 0:
        graham_product = pe * pb
        if graham_product < 15:
            score += 1.5
        elif graham_product < 22.5:
            score += 1

    # B. 재무 건전성
    cr = m.get('current_ratio')
    if cr:
        if cr > 2:
            score += 1.5
        elif cr > 1.5:
            score += 1
        elif cr > 1:
            score += 0.5

    fcf_yield = m.get('free_cash_flow_yield')
    if fcf_yield and fcf_yield > 0:
        if fcf_yield > 0.08:
            score += 1.5
        elif fcf_yield > 0.05:
            score += 1
        elif fcf_yield > 0.03:
            score += 0.5

    # C. 수익 안정성 + 배당
    div_yield = m.get('dividend_yield')
    if div_yield and div_yield > 0:
        if div_yield > 0.04:
            score += 1.5
        elif div_yield > 0.02:
            score += 1
        elif div_yield > 0.01:
            score += 0.5

    roe = m.get('return_on_equity')
    op_margin = m.get('operating_margin')
    if roe and roe > 0 and op_margin and op_margin > 0:
        if roe > 0.10 and op_margin > 0.10:
            score += 1
        elif roe > 0.05 and op_margin > 0.05:
            score += 0.5

    # 52주 저점 대비 위치
    week_52_high = m.get('52_week_high')
    week_52_low = m.get('52_week_low')
    current_price = m.get('50_day_average')
    if week_52_high and week_52_low and current_price:
        range_52 = week_52_high - week_52_low
        if range_52 > 0:
            position = (current_price - week_52_low) / range_52
            if position < 0.25:
                score += 1
            elif position < 0.40:
                score += 0.5

    return min(10, max(0, score))


# ============================================================================
# Phil Fisher 스타일 점수
# ============================================================================

def calculate_fisher_score(metrics, growth_score, quality_score) -> float:
    """
    Phil Fisher 스타일 점수 (Growth + Quality Management)

    평가 구조:
    - R&D/Revenue 비율: 최대 2.5점
    - 매출 성장: 최대 2점
    - 이익률: 최대 2점
    - ROE/ROIC: 최대 2점
    - 마진 개선 추세: 최대 1.5점
    """
    if not metrics:
        return 0

    m = metrics[0] if isinstance(metrics, list) else metrics
    score = 0

    # 1. R&D 투자 비율
    rd_ratio = m.get('research_and_development_ratio')
    has_rd_data = rd_ratio is not None and rd_ratio > 0
    if has_rd_data:
        if rd_ratio > 0.12:
            score += 2.5
        elif rd_ratio > 0.08:
            score += 1.5
        elif rd_ratio > 0.04:
            score += 0.5
        elif rd_ratio < 0.01:
            score -= 1.0

    sector = m.get('sector', '')
    RD_EXPECTED_SECTORS = ['Technology', 'Healthcare', 'Industrials', 'Basic Materials']
    if not has_rd_data and sector in RD_EXPECTED_SECTORS:
        score -= 0.5

    # 2. 매출 성장
    rev_growth = m.get('revenue_growth')
    if rev_growth:
        if rev_growth > 0.20:
            score += 2.0
        elif rev_growth > 0.10:
            score += 1.5
        elif rev_growth > 0.05:
            score += 0.5

    # 3. 높은 이익률
    net_margin = m.get('net_margin')
    if net_margin:
        if net_margin > 0.20:
            score += 2.0
        elif net_margin > 0.15:
            score += 1.5
        elif net_margin > 0.10:
            score += 1.0

    # 4. ROE
    roe = m.get('return_on_equity')
    if roe:
        if roe > 0.20:
            score += 2.0
        elif roe > 0.15:
            score += 1.5
        elif roe > 0.10:
            score += 0.5

    # 5. 성장 점수 반영
    score += growth_score * 0.2

    # 6. 품질 점수 반영
    score += quality_score * 0.1

    # 7. 부채 수준
    debt_to_equity = m.get('debt_to_equity')
    if debt_to_equity is not None:
        if debt_to_equity < 0.3:
            score += 1.0
        elif debt_to_equity > 1.0:
            score -= 1.0

    # 8. 마진 개선 추세
    if isinstance(metrics, list) and len(metrics) >= 2:
        margins = []
        for item in metrics[:3]:
            nm = item.get('net_margin')
            if nm is not None:
                margins.append(nm)
        if len(margins) >= 2 and margins[0] > margins[-1]:
            score += 0.5

    return min(10, max(0, score))


# ============================================================================
# Stanley Druckenmiller 스타일 점수
# ============================================================================

def calculate_druckenmiller_score(momentum_score, growth_score, momentum_details=None, metrics=None) -> float:
    """
    Stanley Druckenmiller 스타일 점수 (Momentum + Conviction)

    점수 구조 (최대 10점):
    - 기본 모멘텀: 최대 5점 (핵심!)
    - 추세 일치/강도: 최대 2.5점
    - 빅 베팅 조건: 최대 2점
    - 돌파 잠재력: 최대 1.5점
    """
    score = 0

    # 1. 기본 모멘텀 점수
    score += momentum_score * 0.5

    # 2. "빅 베팅" 조건
    if momentum_score >= 8:
        score += 2
    elif momentum_score >= 6:
        score += 1

    # 3. 모멘텀 + 성장 시너지
    if momentum_score >= 6 and growth_score >= 5:
        score += 1

    # 4. 추세 일치 분석
    if momentum_details:
        short_momentum = momentum_details.get('short_momentum', 0)
        long_momentum = momentum_details.get('long_momentum', 0)
        rsi = momentum_details.get('rsi', 50)
        trend_strength = momentum_details.get('trend_strength', 0)

        if short_momentum > 0 and long_momentum > 0:
            alignment_strength = min(short_momentum, long_momentum)
            if alignment_strength > 5:
                score += 1.5
            elif alignment_strength > 2:
                score += 1
            else:
                score += 0.5

        if trend_strength and trend_strength > 0.7:
            score += 1
        elif trend_strength and trend_strength > 0.5:
            score += 0.5

        if 40 < rsi < 70:
            score += 0.5

    # 5. 52주 고점 돌파 잠재력
    if metrics:
        m = metrics[0] if isinstance(metrics, list) else metrics
        week_52_high = m.get('52_week_high')
        current = m.get('50_day_average')
        if week_52_high and current and week_52_high > 0:
            proximity_to_high = current / week_52_high
            if proximity_to_high > 0.98:
                score += 1.5
            elif proximity_to_high > 0.95:
                score += 1
            elif proximity_to_high > 0.90:
                score += 0.5

    return min(10, max(0, score))


# ============================================================================
# 투자자 철학 불일치 경고
# ============================================================================

def generate_investor_warnings(ticker: str, investor_scores: dict, metrics: dict) -> list:
    """
    알고리즘 점수와 실제 투자자 철학 간의 잠재적 불일치를 감지하고 경고 생성.

    Returns:
        list: 경고 메시지 리스트
    """
    warnings = []
    m = metrics[0] if isinstance(metrics, list) else metrics
    sector = m.get('sector', '')
    market_cap = m.get('market_cap', 0)
    rev_growth = m.get('revenue_growth')
    pe = m.get('price_to_earnings_ratio')

    # Buffett 관련 경고
    buffett_score = investor_scores.get('buffett', 0)
    if buffett_score >= 6 and sector in ['Basic Materials', 'Energy']:
        warnings.append(f"⚠️ Buffett 높은점수({buffett_score:.1f}) but 원자재/에너지 (철학 충돌)")
    if buffett_score >= 6 and pe and pe > 50:
        warnings.append(f"⚠️ Buffett 높은점수({buffett_score:.1f}) but P/E {pe:.0f} (과대평가)")

    # Lynch 관련 경고
    lynch_score = investor_scores.get('lynch', 0)
    if lynch_score >= 6 and market_cap and market_cap > 200e9:
        cap_str = f"${market_cap/1e9:.0f}B"
        warnings.append(f"⚠️ Lynch 높은점수({lynch_score:.1f}) but 메가캡({cap_str}, 10배 어려움)")
    if lynch_score >= 6 and rev_growth and rev_growth < -0.15:
        warnings.append(f"⚠️ Lynch 높은점수({lynch_score:.1f}) but 매출 {rev_growth*100:.0f}% (떨어지는 칼)")
    if lynch_score >= 6 and sector in ['Basic Materials', 'Energy', 'Industrials']:
        if rev_growth and rev_growth < 0:
            warnings.append(f"⚠️ Lynch 높은점수({lynch_score:.1f}) but 경기순환주 하락기")

    # Graham 관련 경고
    graham_score = investor_scores.get('graham', 0)
    roe = m.get('return_on_equity')
    if graham_score >= 6 and roe and roe < 0:
        warnings.append(f"⚠️ Graham 높은점수({graham_score:.1f}) but ROE 음수 (적자)")

    # 현금흐름 품질 경고
    fcf = m.get('free_cash_flow')
    op_cf = m.get('operating_cashflow')
    op_margin_val = m.get('operating_margin')

    if op_cf is not None and op_cf < 0:
        warnings.append(f"🚨 영업현금흐름 마이너스 (${op_cf/1e6:.0f}M) - 본업 현금소진")
    if fcf is not None and fcf < 0 and (op_cf is None or op_cf >= 0):
        warnings.append(f"⚠️ FCF 마이너스 (${fcf/1e6:.0f}M) - 높은 CapEx 부담")
    if op_margin_val is not None and 0 < op_margin_val < 0.05:
        warnings.append(f"⚠️ 영업마진 극저 ({op_margin_val*100:.1f}%) - 가격결정력 부재")

    return warnings
