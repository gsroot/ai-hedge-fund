---
name: profit-predictor
description: |
  특정 기간 후 최고 수익 예상 종목 선정. 전설적 투자자들의 분석 방식을 종합하여 예측.
  최대 300개 이상의 종목을 배치 처리하여 순위 산정 가능.
  사용 시점: "3개월 후 가장 수익률 좋을 종목은?", 포트폴리오 순위, 투자 우선순위 결정,
  "어떤 종목을 사야 할까?", "AAPL, GOOGL, MSFT 중 뭘 사야해?", 수익률 예측,
  "S&P 500 종목 중 상위 10개 추천", "KOSPI 200 순위"
---

# Profit Predictor Skill

다중 투자자 앙상블 분석을 기반으로 종목 수익률을 예측하고 순위를 산정하는 시스템.
**최대 300개 이상의 종목을 배치 처리**할 수 있으며, 병렬 처리와 캐싱을 지원합니다.

## 워크플로우

### Step 1: 종목 데이터 수집

각 종목에 대해 `investor-analysis` 스킬의 data_fetcher.py 활용:

```python
from .claude.skills.investor-analysis.scripts.data_fetcher import fetch_all_data

for ticker in tickers:
    data = fetch_all_data(ticker, end_date)
```

### Step 2: 다중 투자자 분석

17개 투자자/분석가 서브에이전트를 병렬로 호출:

```python
# 병렬 호출
signals = {}
for agent in investor_agents:
    signals[agent] = Task(
        subagent_type=agent,
        prompt=f"{ticker} 분석. 날짜: {end_date}"
    )
```

### Step 3: 앙상블 점수 계산

`scripts/ranking_algorithm.py` 사용:

```python
from scripts.ranking_algorithm import calculate_ensemble_score, predict_return

ensemble = calculate_ensemble_score(signals)
predicted_return = predict_return(
    ensemble_score=ensemble["ensemble_score"],
    volatility=0.3,  # 기본값
    momentum_factor=0.0  # 모멘텀 에이전트에서 가져오기
)
```

### Step 4: 순위 산정 및 출력

```python
from scripts.ranking_algorithm import rank_tickers

rankings = rank_tickers(ticker_signals, period="3M")
```

## 앙상블 알고리즘

### 신호 수치화

| 신호 | 값 |
|------|-----|
| bullish | +1.0 |
| neutral | 0.0 |
| bearish | -1.0 |

### 투자자별 가중치

| 투자자 | 가중치 | 근거 |
|--------|--------|------|
| Warren Buffett | 1.00 | 장기 복리 성과 최고 |
| Charlie Munger | 0.95 | 버핏 파트너, 정신 모형 |
| Aswath Damodaran | 0.90 | DCF 전문가 |
| Peter Lynch | 0.85 | GARP 선구자 |
| Ben Graham | 0.85 | 가치 투자의 아버지 |
| Stanley Druckenmiller | 0.80 | 매크로, 모멘텀 |
| Mohnish Pabrai | 0.78 | Dhandho 투자자 |
| Michael Burry | 0.75 | 역발상 전문 |
| Bill Ackman | 0.75 | 행동주의 투자 |
| Rakesh Jhunjhunwala | 0.72 | 신흥시장 전문 |
| Cathie Wood | 0.70 | 혁신 투자 (고위험) |

### 앙상블 점수 계산

```
앙상블 점수 = Σ(신호값 × 신뢰도 × 투자자가중치) / Σ(신뢰도 × 가중치)
```

범위: -1.0 ~ +1.0

### 수익률 예측

```python
def predict_return(ensemble_score, volatility, momentum_factor):
    # 기본 수익률: 앙상블 점수 기반 (최대 ±20%)
    base_return = ensemble_score * 0.20

    # 리스크 조정: 변동성이 높으면 수익률 감소
    risk_adjusted = base_return * (1 - volatility * 0.5)

    # 모멘텀 조정
    momentum_adjusted = risk_adjusted * (1 + momentum_factor * 0.3)

    return momentum_adjusted
```

## 신호 결정 기준

| 앙상블 점수 | 신호 | 예상 행동 |
|------------|------|----------|
| > 0.6 | 강한 매수 | 포트폴리오 상위 순위 |
| 0.3 ~ 0.6 | 매수 | 중상위 순위 |
| -0.3 ~ 0.3 | 중립 | 하위 순위 |
| -0.6 ~ -0.3 | 매도 | 제외 권장 |
| < -0.6 | 강한 매도 | 공매도 고려 |

## 출력 형식

```json
{
  "rankings": [
    {
      "rank": 1,
      "ticker": "AAPL",
      "ensemble_score": 0.72,
      "predicted_return": "15.2%",
      "confidence": 78,
      "signal": "bullish",
      "top_bullish": ["warren-buffett-analyst", "charlie-munger-analyst"],
      "top_bearish": [],
      "key_factors": ["강한 ROE (45%)", "안전마진 25%", "일관된 FCF 성장"]
    }
  ],
  "methodology": "17개 투자자 앙상블 + 모멘텀/변동성 조정",
  "period": "3M",
  "analysis_date": "2024-01-15"
}
```

## 사용 예시

### 예시 1: 소규모 종목 비교 (1-10개)
```
"AAPL, GOOGL, MSFT 중 3개월 후 가장 수익 좋을 종목?"
→ 3개 종목 앙상블 분석 후 순위 반환
```

### 예시 2: 포트폴리오 순위 (10-50개)
```
"내 포트폴리오 종목들 수익률 순위 매겨줘: NVDA, TSLA, META, AMZN..."
→ 종목 분석 후 순위 및 예상 수익률 반환
```

### 예시 3: 대규모 스크리닝 (50-300개+)
```
"S&P 500 종목 중 상위 20개 추천해줘"
→ 500개 종목 배치 분석 후 상위 20개 반환

"KOSPI 200 종목 순위 매겨줘"
→ 200개 종목 병렬 처리 후 전체 순위 반환

"나스닥 100 종목 분석해서 가장 유망한 10개 알려줘"
→ 100개 종목 분석 후 Top 10 필터링
```

## 대량 종목 처리 (300+ 종목)

### 배치 처리 아키텍처

```
입력: 300개 종목
    │
    ▼
┌──────────────────────────────┐
│  배치 분할 (50개씩)          │
│  → 6개 배치 생성              │
└──────────────────────────────┘
    │
    ▼
┌──────────────────────────────┐
│  병렬 처리 (10 workers)      │
│  ThreadPoolExecutor          │
└──────────────────────────────┘
    │
    ▼
┌──────────────────────────────┐
│  결과 병합 및 정렬           │
│  앙상블 점수 기준 순위 부여   │
└──────────────────────────────┘
    │
    ▼
출력: 순위가 매겨진 300개 종목
```

### CLI 사용법

```bash
# 기본 사용 (50개 초과 시 자동 배치 처리)
python ranking_algorithm.py --signals all_signals.json --period 3M

# 배치 크기 및 워커 수 조정
python ranking_algorithm.py --signals sp500.json --batch-size 100 --workers 20

# 상위 N개만 출력
python ranking_algorithm.py --signals nasdaq100.json --top 20

# 마크다운 리포트 생성
python ranking_algorithm.py --signals kospi200.json --format markdown --output report.md

# 캐시 정리 후 실행
python ranking_algorithm.py --signals signals.json --clear-cache
```

### 주요 함수

| 함수 | 용도 | 권장 종목 수 |
|------|------|-------------|
| `rank_tickers()` | 소규모 분석 | 1-50개 |
| `rank_tickers_batch()` | 대규모 배치 처리 | 50-500개 |
| `get_top_picks()` | 상위 종목 필터링 | 결과에서 추출 |
| `generate_report()` | 리포트 생성 | 모든 규모 |

### 캐싱 시스템

- 캐시 위치: `~/.cache/profit-predictor/`
- 캐시 유효기간: 24시간
- 자동 정리: 7일 이상 된 캐시 삭제

```python
# 캐시 수동 정리
from ranking_algorithm import clear_cache
cleared = clear_cache(max_age_days=3)  # 3일 이상 된 캐시 삭제
```

### 성능 가이드

| 종목 수 | 예상 처리 시간 | 권장 설정 |
|---------|---------------|-----------|
| 10개 | ~5초 | 기본값 |
| 50개 | ~20초 | 기본값 |
| 100개 | ~40초 | batch_size=50 |
| 200개 | ~80초 | batch_size=50, workers=15 |
| 300개 | ~120초 | batch_size=100, workers=20 |

**참고**: 실제 시간은 API 응답 속도와 시스템 성능에 따라 달라집니다.
