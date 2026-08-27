# 분석가 페르소나 프로필

5개의 전문 분석가 유형과 분석 방법론.

## 목차

1. [Technical Analyst](#technical-analyst)
2. [Fundamentals Analyst](#fundamentals-analyst)
3. [Growth Analyst](#growth-analyst)
4. [Sentiment Analyst](#sentiment-analyst)
5. [News Sentiment Analyst](#news-sentiment-analyst)

---

## Technical Analyst

**분석 유형**: 기술적 분석
**데이터 소스**: 가격, 거래량

### 5가지 전략

#### 1. Trend Following (추세 추종)
- 이동평균 크로스오버 (8일 vs 21일 EMA)
- 가격 vs 50일/200일 SMA
- 골든크로스/데드크로스
- ADX > 25: 강한 추세

#### 2. Mean Reversion (평균 회귀)
- 볼린저 밴드 (20일, 2σ)
- RSI (14일): 과매도 < 30, 과매수 > 70
- Z-Score: ±2 극단값

#### 3. Momentum (모멘텀)
- 1M, 3M, 6M 수익률
- 거래량 확인

#### 4. Volatility (변동성)
- Historical Volatility (연율화)
- ATR (14일)
- Bollinger Band Width

#### 5. Statistical Arbitrage (통계적 차익)
- 선형 회귀 잔차 분석
- Hurst Exponent

### 가중치
| 전략 | 가중치 |
|------|--------|
| Trend Following | 25% |
| Mean Reversion | 20% |
| Momentum | 25% |
| Volatility | 15% |
| Statistical Arbitrage | 15% |

---

## Fundamentals Analyst

**분석 유형**: 펀더멘털 분석
**데이터 소스**: 재무제표

### 4가지 분석 영역

#### 1. Profitability (수익성)
- ROE, ROA, ROIC
- Net/Operating/Gross Margin

**점수 기준**:
- ROE > 20%: 3점
- Operating Margin > 20%: 3점
- Net Margin > 15%: 2점

#### 2. Growth (성장성)
- Revenue Growth (YoY, 3Y, 5Y CAGR)
- Net Income/EPS Growth
- FCF Growth

**점수 기준**:
- Revenue CAGR 5Y > 20%: 3점
- EPS CAGR 5Y > 20%: 3점
- 5년 연속 성장: 2점

#### 3. Financial Health (재무 건전성)
- Current/Quick Ratio
- Debt-to-Equity
- Interest Coverage
- FCF/Revenue

**점수 기준**:
- Current Ratio > 2.0: 2점
- D/E < 0.3: 3점
- Interest Coverage > 10: 2점

#### 4. Valuation (밸류에이션)
- P/E, P/B, P/S
- EV/EBITDA, PEG
- FCF Yield

**점수 기준**:
- PEG < 1.0: 3점
- FCF Yield > 8%: 3점

### 가중치
각 영역 25%씩 동일 가중치

---

## Growth Analyst

**분석 유형**: 성장 분석
**데이터 소스**: 재무제표, 내부자 거래

### 4가지 분석 영역

#### 1. Revenue Growth (매출 성장)
- YoY 성장률
- 3년/5년 CAGR
- 성장 가속도

**점수 기준**:
- YoY > 30%: 4점
- 성장 가속: +1점
- 5년 연속 성장: +2점

#### 2. Earnings Growth (수익 성장)
- Net Income Growth
- EPS Growth
- Operating Income Growth
- FCF Growth

**점수 기준**:
- EPS 성장 > 30%: 4점
- FCF 성장 > Net Income 성장: +2점 (고품질)

#### 3. Margin Expansion (마진 확대)
- Gross Margin 변화
- Operating Margin 변화
- Operating Leverage

**점수 기준**:
- 3년간 > 3%p 확대: 3점
- Operating Leverage 효과: +2점

#### 4. Insider Conviction (내부자 확신)
- 내부자 순매수/순매도
- 경영진 지분율

**점수 기준**:
- 강한 순매수: 3점
- 경영진 지분 > 10%: +1점

### 가중치
| 영역 | 가중치 |
|------|--------|
| Revenue Growth | 30% |
| Earnings Growth | 30% |
| Margin Expansion | 25% |
| Insider Conviction | 15% |

---

## Sentiment Analyst

**분석 유형**: 시장 심리 분석
**데이터 소스**: 내부자 거래, 회사 뉴스

### 2가지 신호 소스

#### 1. Insider Trading (가중치 30%)
- transaction_shares > 0: 매수 → bullish
- transaction_shares < 0: 매도 → bearish

**집계**:
```
insider_signal = bullish_trades > bearish_trades ? "bullish" : "bearish"
```

#### 2. News Sentiment (가중치 70%)
- positive → bullish
- negative → bearish
- neutral → neutral

**집계**:
```
news_signal = bullish_articles > bearish_articles ? "bullish" : "bearish"
```

### 종합 신호 계산
```
weighted_bullish = insider_bullish × 0.3 + news_bullish × 0.7
weighted_bearish = insider_bearish × 0.3 + news_bearish × 0.7
signal = weighted_bullish > weighted_bearish ? "bullish" : "bearish"
```

---

## News Sentiment Analyst

**분석 유형**: 뉴스 심리 분석 (현재 스킬 LLM 기반)
**데이터 소스**: 회사 뉴스, 현재 스킬을 실행 중인 LLM

### 분석 프로세스

#### 1. 뉴스 수집
- 최근 100개 기사 수집
- 제목, 발행일, 기존 sentiment
- 동일 링크 또는 정규화 제목 중복 제거

#### 2. LLM 분석
- 기존 sentiment 유무와 관계없이 기사 최대 5개를 다시 분석
- 종목 관련성(`relevant|unrelated|ambiguous`)을 먼저 판정
- 이벤트 유형, 시장 기대 대비 surprise, 영향 기간을 분리
- 제목 기반 심리 분류
- 신뢰도 점수 (0-100) 함께 반환
- 불명확하거나 근거가 부족하면 `abstain=true`
- 현재 스킬 LLM이 직접 분류하며 외부 모델 API나 고정 모델명을 사용하지 않음

**현재 스킬 LLM 지시문**:
```
"For stock {ticker}, first determine entity relevance. Classify event type,
surprise versus expectations, impact horizon, and sentiment. Abstain when the
headline is ambiguous or insufficient. Provide confidence 0-100 and reasoning."
```

#### 3. 집계
- 무관·애매·abstain·confidence 60 미만은 제외
- `market_price_recap`, `routine_disclosure`는 제외
- 남은 positive → bullish, negative → bearish, neutral → neutral
- confidence 70 이상의 negative는 `risk_flags`에도 기록

#### 4. 신뢰도 계산
```
if LLM 분석 있음:
  confidence = 0.7 × avg_skill_llm_confidence + 0.3 × signal_proportion
else:
  confidence = max(bullish, bearish) / total × 100
```

### 주의사항
- 별도 OpenAI API 호출과 `OPENAI_API_KEY` 사용 금지
- 모델명은 지정하지 않고 현재 스킬 실행 모델을 그대로 사용
- 헤드라인 기반 분석 (본문 미포함)
- 종목 특정 sentiment만 판단
- 뉴스 신호는 기본적으로 위험 경보·설명용이며, 검증 전 순위 성과 향상을 주장하지 않음
- 공급자·keyword의 기존 sentiment는 관련성 검사를 우회하지 못하며 진단용으로만 집계
