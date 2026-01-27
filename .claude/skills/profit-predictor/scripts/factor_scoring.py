"""
멀티팩터 분석 로직

7가지 팩터(가치, 성장, 품질, 모멘텀, 안전성, 센티먼트, 내부자)의
점수를 계산하는 함수들을 제공합니다. 시가총액 카테고리 분류 및 보너스도 포함됩니다.
"""
from config import NEGATIVE_KEYWORDS, POSITIVE_KEYWORDS


# ============================================================================
# 시가총액 카테고리
# ============================================================================

def get_market_cap_category(market_cap):
    """시가총액 기반 카테고리 분류"""
    if not market_cap:
        return None, "N/A"

    cap_b = market_cap / 1e9  # 십억 달러 단위

    if cap_b >= 200:
        return "mega", f"${cap_b:.0f}B"
    elif cap_b >= 10:
        return "large", f"${cap_b:.0f}B"
    elif cap_b >= 2:
        return "mid", f"${cap_b:.1f}B"
    else:
        return "small", f"${cap_b*1000:.0f}M"


def calculate_size_bonus(market_cap, growth_score):
    """
    시가총액 기반 보너스 점수 (피터 린치/준준왈라 스타일)
    - 고성장 소형주: 10배 수익 가능성 → 가산점
    - 대형주: 안정성 → 약간의 가산점
    """
    if not market_cap:
        return 0, []

    category, _ = get_market_cap_category(market_cap)
    score = 0
    factors = []

    if category == "small":
        if growth_score >= 6:
            score += 2
            factors.append("소형 고성장주 (텐배거 후보)")
        elif growth_score >= 3:
            score += 1
            factors.append("소형 성장주")
    elif category == "mid":
        if growth_score >= 4:
            score += 1
            factors.append("중형 성장주")
    elif category == "mega":
        score -= 0.5

    return score, factors


# ============================================================================
# 가치 투자 점수
# ============================================================================

def calculate_value_score(metrics):
    """가치 투자 점수 (버핏/그레이엄/멍거 스타일)"""
    if not metrics:
        return 0, []

    m = metrics[0]
    score = 0
    factors = []

    # P/E 비율
    pe = m.get('price_to_earnings_ratio')
    if pe:
        if 0 < pe < 12:
            score += 4
            factors.append(f"매우 낮은 P/E ({pe:.1f})")
        elif 0 < pe < 18:
            score += 2
            factors.append(f"적정 P/E ({pe:.1f})")
        elif pe > 35:
            score -= 2

    # P/B 비율
    pb = m.get('price_to_book_ratio')
    if pb:
        if 0 < pb < 1.5:
            score += 3
            factors.append(f"저평가 P/B ({pb:.2f})")
        elif 0 < pb < 3:
            score += 1
        elif pb > 8:
            score -= 1

    # EV/EBITDA
    ev_ebitda = m.get('enterprise_value_to_ebitda')
    if ev_ebitda:
        if 0 < ev_ebitda < 8:
            score += 2
            factors.append(f"낮은 EV/EBITDA ({ev_ebitda:.1f})")
        elif 0 < ev_ebitda < 12:
            score += 1

    # FCF Yield
    fcf_yield = m.get('free_cash_flow_yield')
    if fcf_yield:
        if fcf_yield > 0.08:
            score += 3
            factors.append(f"높은 FCF Yield ({fcf_yield*100:.1f}%)")
        elif fcf_yield > 0.05:
            score += 1

    return score, factors


# ============================================================================
# 성장 투자 점수
# ============================================================================

def calculate_growth_score(metrics):
    """성장 투자 점수 (린치/캐시우드 스타일)"""
    if not metrics:
        return 0, []

    m = metrics[0]
    score = 0
    factors = []

    # 매출 성장률
    rev_growth = m.get('revenue_growth')
    if rev_growth:
        if rev_growth > 0.25:
            score += 4
            factors.append(f"고성장 매출 (+{rev_growth*100:.0f}%)")
        elif rev_growth > 0.15:
            score += 2
            factors.append(f"양호한 매출 성장 (+{rev_growth*100:.0f}%)")
        elif rev_growth > 0.08:
            score += 1
        elif rev_growth < 0:
            score -= 2

    # EPS 성장률
    eps_growth = m.get('earnings_per_share_growth')
    if eps_growth:
        if eps_growth > 0.25:
            score += 3
        elif eps_growth > 0.15:
            score += 2
        elif eps_growth > 0.08:
            score += 1

    # PEG 비율 (린치 스타일)
    peg = m.get('peg_ratio')
    if peg:
        if 0 < peg < 0.8:
            score += 4
            factors.append(f"매력적 PEG ({peg:.2f})")
        elif 0 < peg < 1.2:
            score += 2
            factors.append(f"적정 PEG ({peg:.2f})")
        elif peg > 2.5:
            score -= 1

    return score, factors


# ============================================================================
# 품질 점수
# ============================================================================

def calculate_quality_score(metrics):
    """품질 점수 (멍거/피셔 스타일)"""
    if not metrics:
        return 0, []

    m = metrics[0]
    score = 0
    factors = []

    # ROE
    roe = m.get('return_on_equity')
    if roe:
        if roe > 0.25:
            score += 4
            factors.append(f"뛰어난 ROE ({roe*100:.0f}%)")
        elif roe > 0.18:
            score += 2
            factors.append(f"양호한 ROE ({roe*100:.0f}%)")
        elif roe > 0.12:
            score += 1
        elif roe < 0.05:
            score -= 2

    # ROIC
    roic = m.get('return_on_invested_capital')
    if roic:
        if roic > 0.20:
            score += 3
            factors.append(f"높은 ROIC ({roic*100:.0f}%)")
        elif roic > 0.12:
            score += 1

    # 영업이익률
    op_margin = m.get('operating_margin')
    if op_margin:
        if op_margin > 0.25:
            score += 2
            factors.append(f"높은 영업마진 ({op_margin*100:.0f}%)")
        elif op_margin > 0.15:
            score += 1
        elif op_margin < 0.05:
            score -= 1

    # 순이익률
    net_margin = m.get('net_margin')
    if net_margin:
        if net_margin > 0.20:
            score += 2
        elif net_margin > 0.10:
            score += 1

    return score, factors


# ============================================================================
# 모멘텀 점수
# ============================================================================

def calculate_momentum_score(prices):
    """모멘텀 점수 (드러켄밀러 스타일)"""
    if not prices or len(prices) < 60:
        return 0, []

    score = 0
    factors = []

    try:
        current = prices[-1].get('close', 0)
        price_20d = prices[-20].get('close', current) if len(prices) >= 20 else current
        price_60d = prices[-60].get('close', current) if len(prices) >= 60 else current

        # 1개월 모멘텀
        mom_1m = (current - price_20d) / price_20d if price_20d else 0
        if mom_1m > 0.10:
            score += 3
            factors.append(f"강한 1M 모멘텀 (+{mom_1m*100:.0f}%)")
        elif mom_1m > 0.03:
            score += 1
        elif mom_1m < -0.10:
            score -= 2

        # 3개월 모멘텀
        mom_3m = (current - price_60d) / price_60d if price_60d else 0
        if mom_3m > 0.20:
            score += 2
            factors.append(f"강한 3M 모멘텀 (+{mom_3m*100:.0f}%)")
        elif mom_3m > 0.08:
            score += 1
        elif mom_3m < -0.15:
            score -= 2

    except Exception:
        pass

    return score, factors


def calculate_enhanced_momentum_score(prices, lookback_short=20, lookback_long=60):
    """
    강화된 모멘텀 점수 계산 (0-10 스케일)
    - 단기/장기 가격 추세
    - RSI 보정
    - 추세 지속성 보너스
    """
    if not prices or len(prices) < lookback_long:
        return 5.0, {"short_momentum": 0, "long_momentum": 0, "rsi": 50, "trend": "neutral"}

    try:
        closes = [p.get('close', 0) for p in prices]
        if not closes or closes[-1] == 0:
            return 5.0, {"short_momentum": 0, "long_momentum": 0, "rsi": 50, "trend": "neutral"}

        current = closes[-1]

        # 단기 모멘텀 (20일)
        short_price = closes[-lookback_short] if len(closes) >= lookback_short else closes[0]
        short_momentum = (current - short_price) / short_price if short_price > 0 else 0

        # 장기 모멘텀 (60일)
        long_price = closes[-lookback_long] if len(closes) >= lookback_long else closes[0]
        long_momentum = (current - long_price) / long_price if long_price > 0 else 0

        # RSI 계산 (14일)
        rsi = 50
        if len(closes) >= 15:
            gains = []
            losses = []
            for i in range(-14, 0):
                change = closes[i] - closes[i-1]
                if change > 0:
                    gains.append(change)
                    losses.append(0)
                else:
                    gains.append(0)
                    losses.append(abs(change))
            avg_gain = sum(gains) / 14
            avg_loss = sum(losses) / 14
            if avg_loss > 0:
                rs = avg_gain / avg_loss
                rsi = 100 - (100 / (1 + rs))
            else:
                rsi = 100 if avg_gain > 0 else 50

        # 모멘텀 점수 계산 (0-10 스케일)
        # 단기 모멘텀 기여 (최대 4점)
        short_score = 0
        if short_momentum > 0.15:
            short_score = 4
        elif short_momentum > 0.08:
            short_score = 3
        elif short_momentum > 0.03:
            short_score = 2
        elif short_momentum > 0:
            short_score = 1
        elif short_momentum > -0.05:
            short_score = 0.5
        else:
            short_score = 0

        # 장기 모멘텀 기여 (최대 4점)
        long_score = 0
        if long_momentum > 0.25:
            long_score = 4
        elif long_momentum > 0.15:
            long_score = 3
        elif long_momentum > 0.08:
            long_score = 2
        elif long_momentum > 0:
            long_score = 1
        elif long_momentum > -0.10:
            long_score = 0.5
        else:
            long_score = 0

        # RSI 보정 (최대 2점)
        rsi_score = 0
        if 40 <= rsi <= 60:
            rsi_score = 1  # 중립 영역
        elif 30 <= rsi < 40 or 60 < rsi <= 70:
            rsi_score = 1.5  # 적정 영역
        elif rsi < 30:
            rsi_score = 2  # 과매도 (반등 기대)
        elif rsi > 70:
            rsi_score = 0.5  # 과매수 (조정 가능)

        # 추세 지속성 보너스
        trend = "neutral"
        trend_bonus = 0
        if short_momentum > 0 and long_momentum > 0:
            trend = "bullish"
            trend_bonus = 0.5
        elif short_momentum < 0 and long_momentum < 0:
            trend = "bearish"
            trend_bonus = -0.5

        total_score = short_score + long_score + rsi_score + trend_bonus
        total_score = max(0, min(10, total_score))  # 0-10 범위로 제한

        details = {
            "short_momentum": round(short_momentum * 100, 1),
            "long_momentum": round(long_momentum * 100, 1),
            "rsi": round(rsi, 1),
            "trend": trend,
        }

        return round(total_score, 2), details

    except Exception:
        return 5.0, {"short_momentum": 0, "long_momentum": 0, "rsi": 50, "trend": "neutral"}


# ============================================================================
# 안전성 점수
# ============================================================================

def calculate_safety_score(metrics):
    """
    안전성 점수 (파브라이/버핏 스타일)

    평가 항목:
    - 부채비율(D/E), 유동비율, 이자보상배율(EBIT / Interest Expense)
    - cash_ratio (현금 / 유동부채), quick_ratio ((유동자산 - 재고) / 유동부채)
    - 소유권 안정성: 기관/내부자 보유 비율
    """
    if not metrics:
        return 0, []

    m = metrics[0]
    score = 0
    factors = []

    # 부채비율 (D/E)
    debt_equity = m.get('debt_to_equity')
    if debt_equity is not None:
        if debt_equity < 0.3:
            score += 3
            factors.append("낮은 부채")
        elif debt_equity < 0.7:
            score += 1
        elif debt_equity > 2:
            score -= 2
            factors.append("높은 부채 위험")

    # 유동비율
    current_ratio = m.get('current_ratio')
    if current_ratio:
        if current_ratio > 2.5:
            score += 2
            factors.append(f"양호한 유동비율 ({current_ratio:.1f})")
        elif current_ratio > 1.5:
            score += 1
        elif current_ratio < 1:
            score -= 2
            factors.append("유동성 위험")

    # 당좌비율 (Quick Ratio)
    quick_ratio = m.get('quick_ratio')
    if quick_ratio:
        if quick_ratio > 1.5:
            score += 1
        elif quick_ratio < 0.5:
            score -= 1

    # 현금비율 (Cash Ratio)
    cash_ratio = m.get('cash_ratio')
    if cash_ratio:
        if cash_ratio > 0.5:
            score += 2
            factors.append(f"충분한 현금보유 ({cash_ratio:.2f})")
        elif cash_ratio > 0.2:
            score += 1
        elif cash_ratio < 0.1:
            score -= 1

    # 이자보상배율 (Interest Coverage)
    interest_coverage = m.get('interest_coverage')
    if interest_coverage:
        if interest_coverage > 10:
            score += 2
            factors.append(f"충분한 이자보상 ({interest_coverage:.1f}x)")
        elif interest_coverage > 5:
            score += 1
        elif interest_coverage < 2:
            score -= 2
            factors.append("이자보상 위험")

    # 영업현금흐름 비율
    ocf_ratio = m.get('operating_cash_flow_ratio')
    if ocf_ratio:
        if ocf_ratio > 1.0:
            score += 1
            factors.append("강한 영업현금흐름")
        elif ocf_ratio < 0.5:
            score -= 1

    # 배당 (안정성 지표)
    div_yield = m.get('dividend_yield')
    if div_yield and div_yield > 0.02:
        score += 1
        if div_yield > 0.035:
            factors.append(f"안정적 배당 ({div_yield*100:.1f}%)")

    # 기관/내부자 보유 비율
    held_insiders = m.get('held_percent_insiders')
    held_institutions = m.get('held_percent_institutions')
    if held_institutions and held_institutions > 0.7:
        score += 1
    if held_insiders and held_insiders > 0.1:
        score += 1

    return score, factors


# ============================================================================
# 센티먼트 분석 (Peter Lynch, News Sentiment 스타일)
# ============================================================================

def calculate_sentiment_score(news_items: list) -> tuple:
    """
    뉴스 센티먼트 점수 계산 (Peter Lynch 스타일)

    분석 방식:
    - title + summary 결합 분석 (최대 50건)
    - 긍정/부정 키워드 매칭
    - summary 키워드는 1.5배 가중치 적용

    Returns:
        (score, factors): 0-10 범위의 점수와 주요 요인 리스트
    """
    if not news_items:
        return 5, ["뉴스 데이터 없음 (중립)"]

    positive_score = 0
    negative_score = 0
    news_with_keywords = 0

    for item in news_items:
        title = (item.get("title") or "").lower()
        summary = (item.get("summary") or "").lower()

        # 제목에서 키워드 검색
        title_negative = any(word in title for word in NEGATIVE_KEYWORDS)
        title_positive = any(word in title for word in POSITIVE_KEYWORDS)

        # 요약에서 키워드 검색 (1.5배 가중치)
        summary_negative = any(word in summary for word in NEGATIVE_KEYWORDS)
        summary_positive = any(word in summary for word in POSITIVE_KEYWORDS)

        # 점수 계산
        if title_negative:
            negative_score += 1
            news_with_keywords += 1
        if summary_negative:
            negative_score += 0.5
            news_with_keywords += 1

        if title_positive:
            positive_score += 1
            news_with_keywords += 1
        if summary_positive:
            positive_score += 0.5
            news_with_keywords += 1

    total = len(news_items)
    factors = []

    if total == 0:
        return 5, ["뉴스 없음"]

    total_score = positive_score + negative_score
    if total_score > 0:
        negative_ratio = negative_score / total_score
        positive_ratio = positive_score / total_score
    else:
        negative_ratio = 0
        positive_ratio = 0

    coverage_ratio = news_with_keywords / total if total > 0 else 0

    if negative_ratio > 0.6:
        score = 2
        factors.append(f"부정적 뉴스 우세 ({negative_score:.1f}점)")
    elif negative_ratio > 0.4:
        score = 4
        factors.append(f"부정적 뉴스 다수 ({negative_score:.1f}점)")
    elif positive_ratio > 0.6:
        score = 9
        factors.append(f"긍정적 뉴스 우세 ({positive_score:.1f}점)")
    elif positive_ratio > 0.4:
        score = 7
        factors.append(f"긍정적 뉴스 다수 ({positive_score:.1f}점)")
    else:
        score = 5
        factors.append("뉴스 센티먼트 중립")

    factors.append(f"분석 뉴스: {total}개")

    return score, factors


# ============================================================================
# 내부자 거래 점수
# ============================================================================

def calculate_insider_activity_score(insider_trades: list) -> tuple:
    """
    내부자 거래 점수 계산 (Peter Lynch 스타일)

    분석 방식:
    - 최대 100건의 거래 데이터 분석
    - 거래 금액(transaction_value) 기반 가중치 적용
    - Direct vs Indirect 소유권 구분
    - 대규모 매수/매도에 추가 가중치

    Returns:
        (score, factors): 0-10 범위의 점수와 주요 요인 리스트
    """
    if not insider_trades:
        return 5, ["내부자 거래 데이터 없음 (중립)"]

    buy_count = 0
    sell_count = 0
    buy_value = 0
    sell_value = 0
    direct_buys = 0

    for trade in insider_trades:
        tx_type = str(trade.get("transaction_type") or "").lower()
        shares = trade.get("shares")
        value = trade.get("value") or trade.get("transaction_value") or 0
        ownership = str(trade.get("ownership_type") or "").lower()

        try:
            value = abs(float(value)) if value else 0
        except (TypeError, ValueError):
            value = 0

        is_buy = False
        is_sell = False

        if "buy" in tx_type or "purchase" in tx_type or "acquisition" in tx_type:
            is_buy = True
        elif "sale" in tx_type or "sell" in tx_type or "sold" in tx_type:
            is_sell = True
        elif shares is not None:
            try:
                shares_val = float(shares)
                if shares_val > 0:
                    is_buy = True
                elif shares_val < 0:
                    is_sell = True
            except (TypeError, ValueError):
                pass

        if is_buy:
            buy_count += 1
            buy_value += value
            if "direct" in ownership:
                direct_buys += 1
        elif is_sell:
            sell_count += 1
            sell_value += value

    total_count = buy_count + sell_count
    total_value = buy_value + sell_value
    factors = []

    if total_count == 0:
        return 5, ["유효한 내부자 거래 없음"]

    buy_count_ratio = buy_count / total_count
    buy_value_ratio = buy_value / total_value if total_value > 0 else buy_count_ratio

    if total_value > 0:
        buy_ratio = (buy_count_ratio * 0.5) + (buy_value_ratio * 0.5)
    else:
        buy_ratio = buy_count_ratio

    if buy_ratio > 0.7:
        score = 9
        factors.append(f"강한 내부자 매수 ({buy_count}건)")
    elif buy_ratio > 0.5:
        score = 7
        factors.append(f"내부자 순매수 ({buy_count}건 매수)")
    elif buy_ratio > 0.3:
        score = 5
        factors.append("내부자 거래 혼재")
    else:
        score = 3
        factors.append(f"내부자 매도 우위 ({sell_count}건)")

    if buy_value > 1_000_000:
        score = min(10, score + 1)
        factors.append(f"대규모 매수 (${buy_value/1_000_000:.1f}M)")
    elif sell_value > 5_000_000:
        score = max(1, score - 1)
        factors.append(f"대규모 매도 (${sell_value/1_000_000:.1f}M)")

    if direct_buys > 2:
        score = min(10, score + 0.5)
        factors.append(f"직접소유 매수 {direct_buys}건")

    factors.append(f"총 {total_count}건 분석")

    return score, factors
