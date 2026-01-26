---
name: backtesting
description: |
  포트폴리오 백테스팅 시스템. Yahoo Finance 기반 히스토리컬 데이터로 투자 전략 시뮬레이션.
  모멘텀 전략, profit-predictor 전략, 하이브리드 전략 지원. Sharpe/Sortino Ratio, Max Drawdown 등 성과 지표 계산.
  사용 시점: "백테스트 해줘", "전략 시뮬레이션", "과거 데이터로 테스트", "수익률 검증",
  "AAPL, MSFT 백테스트", "모멘텀 전략 테스트"
---

# Backtesting Skill

Yahoo Finance 기반의 포트폴리오 백테스팅 시스템.
투자 전략을 과거 데이터로 시뮬레이션하여 성과를 검증합니다.

## 빠른 시작

### 스크립트 실행

```bash
# 기본 모멘텀 전략 백테스트
uv run python .claude/skills/backtesting/scripts/backtest.py \
  --tickers AAPL,MSFT,GOOGL \
  --start 2024-01-01 \
  --end 2024-12-31

# profit-predictor 전략 사용
uv run python .claude/skills/backtesting/scripts/backtest.py \
  --tickers AAPL,MSFT,NVDA \
  --start 2024-01-01 \
  --end 2024-12-31 \
  --strategy predictor

# S&P 500 시가총액 상위 50개 hybrid 전략 (권장)
uv run python .claude/skills/backtesting/scripts/backtest.py \
  --index sp500 \
  --top 50 \
  --sort-by-cap \
  --strategy hybrid \
  --start 2024-06-01 \
  --end 2024-12-31 \
  --rebalance monthly

# NASDAQ 100 전체 종목 백테스트
uv run python .claude/skills/backtesting/scripts/backtest.py \
  --index nasdaq100 \
  --start 2024-06-01 \
  --end 2024-12-31 \
  --strategy predictor \
  --rebalance monthly

# FAANG 종목 월별 리밸런싱
uv run python .claude/skills/backtesting/scripts/backtest.py \
  --index faang \
  --start 2023-01-01 \
  --end 2024-12-31 \
  --rebalance monthly \
  --capital 500000

# 결과 JSON 저장
uv run python .claude/skills/backtesting/scripts/backtest.py \
  --tickers NVDA,TSLA \
  --start 2024-01-01 \
  --end 2024-06-30 \
  --output results.json
```

## 기능

### 거래 전략

| 전략 | 설명 | 특징 |
|------|------|------|
| **momentum** | 모멘텀 + RSI 기반 | 20일 모멘텀 + 14일 RSI로 매수/매도 신호 |
| **predictor** | profit-predictor 연동 | 앙상블 투자자 점수 기반 신호 생성 |
| **hybrid** | 펀더멘털 + 모멘텀 결합 | 50% 펀더멘털 + 50% 모멘텀, 상대 순위 기반 **(권장)** |

### 지원 기능

- **롱/숏 포지션**: 롱 매수/매도, 공매도/커버 지원
- **마진 관리**: 공매도 시 마진 요구사항 적용
- **리밸런싱**: 일별/주별/월별 리밸런싱 주기 선택
- **벤치마크 비교**: SPY 대비 초과 수익률(α) 계산
- **성과 지표**: Sharpe, Sortino, Max Drawdown 등

### 성과 지표

| 지표 | 설명 | 계산 방식 |
|------|------|----------|
| **Sharpe Ratio** | 위험 대비 수익률 | (수익률 - 무위험수익률) / 표준편차 × √252 |
| **Sortino Ratio** | 하방 위험 대비 수익률 | 초과수익률 / 하방편차 × √252 |
| **Max Drawdown** | 최대 낙폭 | (고점 - 저점) / 고점 × 100 |
| **Total Return** | 총 수익률 | (최종가치 - 초기자본) / 초기자본 × 100 |
| **Annualized Return** | 연환산 수익률 | (1 + 총수익률)^(365/일수) - 1 |
| **Win Rate** | 승률 | 수익 거래 / 총 거래 × 100 |

## CLI 옵션

| 옵션 | 설명 | 기본값 |
|------|------|--------|
| `--tickers` | 종목 리스트 (콤마 구분) | - |
| `--index` | 인덱스 또는 사전 정의 그룹 | - |
| `--top` | 인덱스에서 상위 N개만 사용 | 0 (전체) |
| `--sort-by-cap` | 시가총액 기준 정렬 **(권장)** | false |
| `--start` | 시작 날짜 (YYYY-MM-DD) | 필수 |
| `--end` | 종료 날짜 (YYYY-MM-DD) | 필수 |
| `--capital` | 초기 자본 | 100000 |
| `--strategy` | 전략 (momentum, predictor, hybrid) | momentum |
| `--rebalance` | 리밸런싱 주기 (daily, weekly, monthly) | weekly |
| `--benchmark` | 벤치마크 티커 | SPY |
| `--margin` | 마진 요구율 | 0.5 |
| `--workers` | 병렬 처리 워커 수 | 10 |
| `--output` | 결과 JSON 저장 경로 | - |

## 지원 인덱스

| 인덱스 | 설명 | 종목 수 |
|--------|------|---------|
| `sp500` | S&P 500 전체 (Wikipedia 기반) | ~500개 |
| `nasdaq100` | NASDAQ 100 전체 | ~100개 |
| `sp500-top10` | S&P 500 시가총액 상위 10개 | 10개 |
| `nasdaq-top10` | NASDAQ 시가총액 상위 10개 | 10개 |
| `faang` | META, AAPL, AMZN, NFLX, GOOGL | 5개 |

### 사전 정의 종목 그룹 (시가총액 기준)

| 그룹 | 종목 |
|------|------|
| `sp500-top10` | AAPL, MSFT, GOOGL, AMZN, NVDA, META, TSLA, BRK-B, UNH, JPM |
| `nasdaq-top10` | AAPL, MSFT, GOOGL, AMZN, NVDA, META, TSLA, AVGO, COST, NFLX |
| `faang` | META, AAPL, AMZN, NFLX, GOOGL |

**참고**: `sp500`, `nasdaq100` 인덱스는 기본적으로 알파벳 순으로 정렬됩니다.
시가총액 기준 상위 종목을 원하면 `--sort-by-cap` 옵션을 사용하세요.

```bash
# 시가총액 기준 NASDAQ 100 상위 30개로 hybrid 전략 백테스트 (권장)
uv run python backtest.py --index nasdaq100 --top 30 --sort-by-cap --strategy hybrid \
  --rebalance monthly --start 2024-06-01 --end 2024-12-31
```

## 출력 예시

```
======================================================================
📊 백테스트 시작: 2024-01-01 ~ 2024-12-31
   종목: AAPL, MSFT, GOOGL
   초기 자본: $100,000
   전략: momentum
   리밸런싱: weekly
======================================================================

📥 가격 데이터 로딩 중...
📅 총 252일 중 52회 리밸런싱 예정

   진행: 10% | 날짜: 2024-01-26 | 포트폴리오: $102,500
   진행: 20% | 날짜: 2024-03-15 | 포트폴리오: $108,200
   ...

======================================================================
📈 백테스트 결과
======================================================================

💰 포트폴리오 성과
   초기 자본:      $        100,000
   최종 가치:      $        125,430
   총 수익률:              25.43%
   연환산 수익률:          25.43%

📊 벤치마크 비교 (SPY)
   벤치마크 수익률:        22.15%
   초과 수익 (α):          3.28%

📉 위험 지표
   Sharpe Ratio:            1.85
   Sortino Ratio:           2.42
   Max Drawdown:           -8.75%
   MDD 날짜:         2024-04-19

📋 거래 통계
   총 거래 수:               45
   승률:                   62.2%

📦 최종 포지션
   AAPL: Long 150주, Short 0주
   MSFT: Long 80주, Short 0주
   GOOGL: Long 0주, Short 0주
   현금: $15,230

======================================================================
```

## JSON 출력 형식

```json
{
  "metrics": {
    "sharpe_ratio": 1.85,
    "sortino_ratio": 2.42,
    "max_drawdown": -8.75,
    "max_drawdown_date": "2024-04-19",
    "total_return": 25.43,
    "annualized_return": 25.43,
    "win_rate": 62.2,
    "total_trades": 45
  },
  "benchmark_return": 22.15,
  "final_value": 125430.0,
  "portfolio_values": [
    {"date": "2024-01-02", "value": 100000.0},
    {"date": "2024-01-03", "value": 100250.0},
    ...
  ],
  "trade_history": [
    {
      "date": "2024-01-08",
      "ticker": "AAPL",
      "action": "buy",
      "quantity": 50,
      "price": 185.32,
      "confidence": 0.72
    },
    ...
  ]
}
```

## 아키텍처

```
┌─────────────────────────────────────────────┐
│            BacktestEngine                   │
├─────────────────────────────────────────────┤
│  1. 가격 데이터 로딩 (yfinance batch)       │
│  2. 리밸런싱 날짜 계산                      │
│  3. 일별 시뮬레이션 루프                    │
│     ├─ 신호 생성 (momentum/predictor/hybrid)│
│     ├─ 포지션 크기 계산                     │
│     ├─ 거래 실행 (Portfolio)                │
│     └─ 포트폴리오 가치 기록                 │
│  4. 성과 지표 계산                          │
│  5. 벤치마크 비교                           │
└─────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────┐
│            Portfolio                        │
├─────────────────────────────────────────────┤
│  - 현금 관리                                │
│  - 롱/숏 포지션 관리                        │
│  - 마진 관리                                │
│  - 실현 손익 추적                           │
│  - 총 가치 계산                             │
└─────────────────────────────────────────────┘
```

## 전략 상세

### 모멘텀 전략

```python
# 20일 모멘텀
momentum = current_price / price_20days_ago - 1

# 14일 RSI
rsi = 100 - (100 / (1 + avg_gain / avg_loss))

# 매수 조건
if momentum > 0.1 and rsi < 70:
    action = BUY

# 매도 조건
if momentum < -0.1 and rsi > 30:
    action = SELL
```

### profit-predictor 전략

profit-predictor의 앙상블 분석 결과를 **상대적 순위 기반**으로 활용:

```python
# 모든 종목 점수 계산 후 순위 결정
ticker_scores = [(ticker, analyze_single_ticker(ticker, date)) for ticker in tickers]
ticker_scores.sort(by_score, reverse=True)

# 상대적 순위로 신호 생성
top_40% → BUY (신뢰도: 순위에 비례)
middle  → HOLD
bottom_20% → SELL
```

| 순위 | 액션 | 신뢰도 |
|------|------|--------|
| 상위 40% | BUY | 0.5~1.0 (높은 순위일수록 높음) |
| 중간 | HOLD | 0.5 |
| 하위 20% | SELL | 0.3~0.6 |

**장점**: 절대 임계값 대신 상대 순위 사용으로 항상 일정 수의 거래 발생

### hybrid 전략 (권장)

펀더멘털과 모멘텀을 50:50으로 결합한 하이브리드 전략:

```python
# 펀더멘털 점수: profit-predictor 앙상블 분석
fundamental_score = analyze_single_ticker(ticker, date)  # 0~10

# 모멘텀 점수: 가격 추세 + RSI
momentum_score = calculate_momentum_score(ticker, price_df)  # 0~10
  - 단기 모멘텀 (20일): 가격 추세
  - 장기 모멘텀 (60일): 중기 추세
  - RSI 보정: 과매수/과매도 조정
  - 추세 보너스: 상승 추세면 가점

# 하이브리드 점수
hybrid_score = fundamental_score * 0.5 + momentum_score * 0.5

# 상대 순위로 신호 생성
top_30% → BUY
middle  → HOLD
bottom_20% → SELL
```

**장점**:
- 펀더멘털만으로 놓칠 수 있는 모멘텀 주도 상승장 (TSLA, NVDA 등) 포착
- 모멘텀만으로 빠질 수 있는 가치 함정 회피
- 시가총액 정렬과 결합 시 최적 성과

## 데이터 소스

- **가격 데이터**: Yahoo Finance (`yf.download` 배치 처리)
- **벤치마크**: SPY (S&P 500 ETF)
- **무위험 수익률**: 4.34% (미국 국채 수익률 기준)

## 실제 백테스트 결과 예시

### NASDAQ 100 상위 30 (2024 하반기, hybrid + 시가총액 정렬) - 권장 설정
```
💰 포트폴리오 성과
   초기 자본:      $        100,000
   최종 가치:      $        125,396
   총 수익률:                25.40%
   연환산 수익률:            47.92%

📊 벤치마크 비교 (SPY)
   벤치마크 수익률:          12.53%
   초과 수익 (α):            12.87%

📉 위험 지표
   Sharpe Ratio:              1.34
   Sortino Ratio:             1.77
   Max Drawdown:            -18.07%

📦 최종 포지션
   NVDA, GOOGL, GOOG, MSFT, META, AVGO 집중 보유
```

### S&P 500 상위 50 (2024 하반기, hybrid + 시가총액 정렬)
```
💰 포트폴리오 성과
   초기 자본:      $        100,000
   최종 가치:      $        117,979
   총 수익률:                17.98%
   연환산 수익률:            33.11%

📊 벤치마크 비교 (SPY)
   벤치마크 수익률:          12.53%
   초과 수익 (α):             5.45%

📉 위험 지표
   Sharpe Ratio:              1.15
   Max Drawdown:            -16.69%
```

### 전략 비교 (NASDAQ 100 --top 100, 2024 하반기)

| 전략 | 총 수익률 | 벤치마크 대비 (α) | Sharpe Ratio |
|------|----------|------------------|--------------|
| predictor (알파벳순) | 2.33% | **-10.19%** | 0.09 |
| hybrid + 시가총액 정렬 | 25.40% | **+12.87%** | 1.34 |

**핵심 개선 포인트**:
1. 알파벳순(MMM, AOS...)→시가총액순(NVDA, AAPL...) 정렬
2. 펀더멘털만→펀더멘털+모멘텀 결합으로 TSLA, NVDA 등 포착

## 성능 최적화

### 병렬 처리

대규모 종목 분석 시 `--workers` 옵션으로 병렬 처리 워커 수를 조절합니다:

```bash
# 기본값 (10 workers)
uv run python backtest.py --index nasdaq100 --strategy predictor ...

# 더 많은 워커 사용 (빠르지만 API rate limit 주의)
uv run python backtest.py --index sp500 --top 100 --workers 20 --strategy predictor ...
```

### 성능 벤치마크

| 종목 수 | 리밸런싱 | 순차 처리 예상 | 병렬 처리 (10 workers) | 속도 향상 |
|---------|----------|---------------|----------------------|----------|
| 10개 | 12회 | ~2.5분 | ~30초 | ~5x |
| 100개 | 12회 | ~26분 | ~6분 | ~4x |
| 100개 | 4회 | ~8분 | **~2분** | ~4x |

### 최적화 팁

1. **리밸런싱 주기**: `monthly` > `weekly` > `daily` (적을수록 빠름)
2. **종목 수 제한**: `--top N` 옵션으로 분석 종목 제한
3. **워커 수**: API rate limit에 따라 10~20 권장
4. **캐시 활용**: 동일 날짜 재실행 시 캐시 적용됨

## 주의사항

1. **백테스트 한계**: 과거 성과가 미래 수익을 보장하지 않음
2. **슬리피지**: 실제 거래 시 슬리피지, 수수료가 발생
3. **유동성**: 소형주의 경우 실제 체결 어려울 수 있음
4. **생존자 편향**: 현재 존재하는 종목만 테스트
5. **데이터 지연**: Yahoo Finance 데이터는 약간의 지연 가능

## 사용 예시

### 예시 1: 기본 백테스트
```
"AAPL, MSFT, GOOGL을 2024년 한 해 동안 백테스트해줘"
→ uv run python backtest.py --tickers AAPL,MSFT,GOOGL --start 2024-01-01 --end 2024-12-31
```

### 예시 2: NASDAQ 100 전체 백테스트
```
"NASDAQ 100 전체 종목으로 profit-predictor 전략 백테스트"
→ uv run python backtest.py --index nasdaq100 --start 2024-06-01 --end 2024-12-31 --strategy predictor --rebalance monthly
```

### 예시 3: S&P 500 상위 50개 백테스트 (권장)
```
"S&P 500에서 시가총액 상위 50개 종목으로 hybrid 전략 백테스트"
→ uv run python backtest.py --index sp500 --top 50 --sort-by-cap --strategy hybrid --start 2024-06-01 --end 2024-12-31 --rebalance monthly
```

### 예시 4: 장기 백테스트
```
"FAANG 종목으로 3년간 월별 리밸런싱 백테스트"
→ uv run python backtest.py --index faang --start 2022-01-01 --end 2024-12-31 --rebalance monthly
```

### 예시 5: 고자본 테스트
```
"50만 달러로 S&P 500 상위 10개 종목 백테스트"
→ uv run python backtest.py --index sp500-top10 --start 2024-01-01 --end 2024-12-31 --capital 500000
```
